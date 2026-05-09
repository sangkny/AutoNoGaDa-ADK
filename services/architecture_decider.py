"""DEBATE 전략으로 아키텍처 선택안을 만들고 Lore 를 DB 에 남김."""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from agents.base import LoreEntry
from agents.orchestrator import Orchestrator, OrchestraStrategy
from ontology.base import OntologyDomain

from models.software import SoftwareLoreDecision

log = logging.getLogger("services.architecture_decider")

_REC_PATTERN = re.compile(
    r"RECOMMENDATION:\s*(.+?)(?:\n|$)",
    re.IGNORECASE | re.MULTILINE,
)
_RAT_PATTERN = re.compile(
    r"RATIONALE:\s*(.+?)(?=\n(?:[A-Z][A-Za-z0-9_ ]{0,40}):\s*\n|\n(?:[A-Z][A-Za-z0-9_]{2,40}):\s|\Z)",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)


def _build_debate_task(requirement: str) -> str:
    return (
        "당신은 시니어 소프트웨어 아키텍트입니다. 아래 요구(트레이드오프)를 읽고 "
        "합리적인 한 가지 선택을 제안하세요.\n\n"
        "반드시 다음 레이블(영문)·순서로만 답하세요:\n\n"
        "RECOMMENDATION:\n"
        "(한 줄: 채택한 방안 이름)\n\n"
        "RATIONALE:\n"
        "(근거를 3~6문장으로 한국어로 서술. 주요 단점 완화책이 있으면 한 문장 포함.)\n\n"
        "--- 요구 ---\n"
        f"{requirement.strip()}\n"
    )


def parse_architecture_answer(text: str) -> tuple[str, str]:
    raw = (text or "").strip()
    if not raw:
        return "", ""

    m_rec = _REC_PATTERN.search(raw)
    rec = (m_rec.group(1).strip() if m_rec else "").strip()

    m_rat = _RAT_PATTERN.search(raw)
    rationale = ""
    if m_rat:
        rationale = " ".join(m_rat.group(1).split())

    if not rec:
        first = raw.split("\n")[0][:500]
        rec = first
    if not rationale:
        rationale = raw[:4000]

    return rec[:2000], rationale[:8000]


def lore_entries_as_json(entries: list[LoreEntry], max_rows: int = 80) -> str:
    rows: list[dict[str, Any]] = []
    for e in entries[:max_rows]:
        rows.append(
            {
                "task_id":    e.task_id,
                "agent":      e.agent.value,
                "action":     e.action,
                "input_hash": e.input_hash,
                "decision":   e.decision,
                "model_used": e.model_used,
                "passed":     e.passed,
                "iteration":  e.iteration,
                "timestamp":  e.timestamp,
            },
        )
    return json.dumps(rows, ensure_ascii=False)


class ArchitectureDecider:
    async def decide(
        self,
        db: AsyncSession,
        requirement: str,
    ) -> dict[str, Any]:
        decision_id = str(uuid.uuid4())
        orch = Orchestrator(
            domain=OntologyDomain.SOFTWARE,
            strategy=OrchestraStrategy.DEBATE,
            max_iterations=2,
            task_id=decision_id[:8],
        )
        task_body = _build_debate_task(requirement)

        try:
            result = await orch.execute(task_body)
        except Exception:
            log.exception("architecture DEBATE 실행 실패")
            row = SoftwareLoreDecision(
                id=decision_id,
                decision_type="architecture_debate",
                requirement=requirement,
                recommendation=None,
                rationale=None,
                raw_output=None,
                orchestrator_passed=False,
                strategy="debate",
                domain="software",
                orchestrator_task_id=orch.task_id,
                error_message="Orchestrator.execute 예외 (로그 참고)",
                lore_json=None,
            )
            db.add(row)
            await db.flush()
            return self._payload(
                decision_id,
                orch.task_id,
                False,
                "",
                "",
                "Orchestrator.execute 예외 (로그 참고)",
                lore_preview=[],
                debate_note=self._debate_note(),
            )

        raw_out = ""
        if result.output is not None:
            raw_out = str(result.output).strip()

        recommendation, rationale = parse_architecture_answer(raw_out)

        error_msg = (result.error or "").strip()
        if not recommendation and not error_msg:
            error_msg = "파싱된 RECOMMENDATION 없음"

        lore_json_str = lore_entries_as_json(result.lore or [])
        if len(lore_json_str) > 62_000:
            lore_json_str = lore_entries_as_json(
                (result.lore or [])[:20],
                max_rows=20,
            )

        row = SoftwareLoreDecision(
            id=decision_id,
            decision_type="architecture_debate",
            requirement=requirement,
            recommendation=recommendation or None,
            rationale=rationale or None,
            raw_output=raw_out[:48000] or None,
            orchestrator_passed=bool(result.passed),
            strategy=result.strategy.value,
            domain=result.domain.value,
            orchestrator_task_id=result.task_id,
            error_message=error_msg or None,
            lore_json=lore_json_str or None,
        )
        db.add(row)
        await db.flush()

        return self._payload(
            decision_id,
            result.task_id,
            bool(result.passed),
            recommendation,
            rationale,
            error_msg,
            lore_preview=self._lore_preview_list(result.lore or []),
            debate_note=self._debate_note(),
        )

    @staticmethod
    def _debate_note() -> str:
        return (
            "내부 전략 DEBATE: FAST(효율·실용)와 HEAVY(품질·정확) 모델이 생성안을 "
            "각각 평가한 뒤 Orchestrator 규칙으로 최종안을 확정합니다."
        )

    @staticmethod
    def _lore_preview_list(entries: list[LoreEntry], limit: int = 24) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for e in entries[:limit]:
            out.append(
                {
                    "agent":     e.agent.value,
                    "action":    e.action,
                    "decision":  e.decision[:300],
                    "passed":    e.passed,
                    "iteration": e.iteration,
                },
            )
        return out

    def _payload(
        self,
        decision_id: str,
        orch_task_id: str,
        passed: bool,
        recommendation: str,
        rationale: str,
        error: str,
        lore_preview: list[dict[str, Any]],
        debate_note: str,
    ) -> dict[str, Any]:
        return {
            "decision_id":           decision_id,
            "orchestrator_task_id":  orch_task_id,
            "orchestrator_passed":   passed,
            "recommendation":        recommendation or "",
            "rationale":             rationale or "",
            "strategy":              "debate",
            "domain":                "software",
            "debate_note":           debate_note,
            "error":                 error or None,
            "lore_preview":          lore_preview,
        }
