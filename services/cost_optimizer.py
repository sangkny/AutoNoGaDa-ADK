"""비용·모델 라우팅 — for_cost() + 사용 로그."""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any

from ontology.validator import OntologyValidator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models.adk_kb import ModelUsageLog, MonthlyBudget

log = logging.getLogger("services.cost_optimizer")


class Complexity(str, Enum):
    SIMPLE = "simple"
    MEDIUM = "medium"
    COMPLEX = "complex"
    CRITICAL = "critical"


@dataclass
class ModelSelection:
    task: str
    complexity: str
    selected_model: str
    estimated_tokens: int
    budget_usd: float
    ontology_passed: bool = True
    ontology_summary: str = ""


class CostOptimizerService:
    """복잡도 기반 모델 문자열 선택 + Ontology COST 검증."""

    RATES_PER_TOKEN: dict[str, float] = {
        "local":     0.0,
        "openai":    0.15 / 1_000_000.0,
        "anthropic": 0.25 / 1_000_000.0,
        "google":    0.075 / 1_000_000.0,
        "azure":     0.14 / 1_000_000.0,
    }

    def analyze_complexity(self, task: str) -> Complexity:
        t = (task or "").lower()
        critical_kw = [
            "의료", "환자", "암호", "보안",
            "medical", "security", "patient",
        ]
        if any(k.lower() in t for k in critical_kw):
            return Complexity.CRITICAL
        n = len(task or "")
        if n < 50:
            return Complexity.SIMPLE
        if n < 150:
            return Complexity.MEDIUM
        return Complexity.COMPLEX

    def _estimate_tokens(self, task: str) -> int:
        base = max(64, int(len(task or "") * 0.35) + 128)
        return min(base, 12_000)

    def _pick_model(self, cmpl: Complexity) -> str:
        if cmpl == Complexity.SIMPLE or cmpl == Complexity.MEDIUM:
            return "LOCAL_FAST/google/gemma-4-e4b"
        if cmpl == Complexity.COMPLEX:
            return "HEAVY/gemma-4-26b-a4b"
        return "CONSENSUS/gemma-4-26b-a4b"

    async def select_model(
        self,
        task: str,
        budget_usd: float | None = None,
    ) -> ModelSelection:
        settings = get_settings()
        budget = float(budget_usd if budget_usd is not None else 1_000_000.0)
        cmpl = self.analyze_complexity(task)
        model = self._pick_model(cmpl)

        payload: dict[str, Any] = {
            "task":              (task or "")[:1200],
            "complexity":        cmpl.value,
            "selected_model":    model,
            "estimated_tokens":  self._estimate_tokens(task),
            "budget_usd":      budget,
        }

        v = await OntologyValidator.for_cost().validate(payload)
        ont_ok = v.passed
        summary = v.summary
        if not ont_ok:
            if cmpl == Complexity.CRITICAL:
                model = "CONSENSUS/gemma-4-26b-a4b"
            elif "COST-DEP-002" in summary or any(
                e.code == "COST-DEP-002" for e in v.errors
            ):
                model = "LOCAL_FAST/google/gemma-4-e4b"
            payload["selected_model"] = model
            v2 = await OntologyValidator.for_cost().validate(payload)
            ont_ok = v2.passed
            summary = v2.summary
            if not ont_ok:
                log.warning("Cost Ontology 재검증 후에도 실패: %s", summary)

        return ModelSelection(
            task=payload["task"],
            complexity=cmpl.value,
            selected_model=model,
            estimated_tokens=int(payload["estimated_tokens"]),
            budget_usd=budget,
            ontology_passed=ont_ok,
            ontology_summary=summary,
        )

    def calculate_cost(self, tokens: int, provider: str) -> float:
        p = (provider or "local").lower().strip()
        rate = self.RATES_PER_TOKEN.get(p, 0.0)
        return float(tokens) * rate

    async def record_usage(
        self,
        db: AsyncSession,
        *,
        task_id: str | None,
        selection: ModelSelection,
        actual_tokens: int | None = None,
    ) -> None:
        settings = get_settings()
        pv = (settings.llm_provider or "local").lower()
        est = int(selection.estimated_tokens)
        tok = int(actual_tokens if actual_tokens is not None else est)
        cost_usd = self.calculate_cost(tok, pv)
        db.add(
            ModelUsageLog(
                id=str(uuid.uuid4()),
                task_id=task_id,
                complexity=selection.complexity,
                selected_model=selection.selected_model,
                estimated_tokens=est,
                actual_cost_usd=cost_usd,
                ontology_passed=selection.ontology_passed,
            ),
        )
        await self._add_spent(db, cost_usd)

    async def _add_spent(self, db: AsyncSession, delta: float) -> None:
        ym = date.today().strftime("%Y-%m")
        row = await db.scalar(
            select(MonthlyBudget).where(MonthlyBudget.year_month == ym),
        )
        if row:
            row.spent_usd = float(row.spent_usd or 0) + float(delta)
            return
        settings = get_settings()
        default_b = float(getattr(settings, "monthly_budget_usd", 10_000.0))
        db.add(
            MonthlyBudget(
                year_month=ym,
                budget_usd=default_b,
                spent_usd=float(delta),
            ),
        )

    async def summary(self, db: AsyncSession) -> dict[str, Any]:
        from sqlalchemy import func

        n = await db.scalar(select(func.count()).select_from(ModelUsageLog))
        n_ok = await db.scalar(
            select(func.count()).select_from(ModelUsageLog).where(
                ModelUsageLog.ontology_passed.is_(True),
            ),
        )
        total_n = int(n or 0)
        ok_n = int(n_ok or 0)
        rate = (ok_n / total_n * 100.0) if total_n else 100.0
        ym = date.today().strftime("%Y-%m")
        bud = await db.scalar(
            select(MonthlyBudget).where(MonthlyBudget.year_month == ym),
        )
        alert = ""
        pct = 0.0
        if bud:
            b = float(bud.budget_usd or 0)
            s = float(bud.spent_usd or 0)
            if b > 0:
                pct = s / b * 100.0
                if pct >= 80:
                    alert = "월 예산의 80%를 초과했습니다."
        return {
            "logged_calls":      total_n,
            "ontology_passed":   ok_n,
            "ontology_rate_pct": round(rate, 2),
            "year_month":        ym,
            "budget_usd":        float(bud.budget_usd) if bud else None,
            "spent_usd":         float(bud.spent_usd) if bud else None,
            "spent_pct":         round(pct, 2),
            "budget_alert":      alert,
        }

    async def set_monthly_budget(self, db: AsyncSession, budget_usd: float) -> dict[str, Any]:
        ym = date.today().strftime("%Y-%m")
        row = await db.scalar(
            select(MonthlyBudget).where(MonthlyBudget.year_month == ym),
        )
        if row:
            row.budget_usd = float(budget_usd)
        else:
            db.add(
                MonthlyBudget(
                    year_month=ym,
                    budget_usd=float(budget_usd),
                    spent_usd=0.0,
                ),
            )
        await db.flush()
        return {"year_month": ym, "budget_usd": float(budget_usd)}

    def budget_warning_for_rate(self, spent_ratio: float) -> str:
        if spent_ratio >= 0.8:
            return "예산 80% 경고"
        return ""
