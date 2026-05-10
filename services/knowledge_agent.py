"""지식베이스 에이전트 — for_knowledge() + pgvector 유사 검색."""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from llm.client import LLMClient
from ontology.validator import OntologyValidator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.adk_kb import AdkCodeExecution, AdkFailurePattern, EMBED_DIM

log = logging.getLogger("services.knowledge_agent")


def _kb_language(lang: str) -> str:
    k = (lang or "python").lower().strip()
    if k not in {"python", "typescript", "rust"}:
        return "python"
    return k


class KnowledgeAgent:
    """실행 결과 임베딩 저장·유사 작업 검색."""

    async def index_execution(
        self,
        db: AsyncSession,
        *,
        task_id: str | None,
        task: str,
        result: str,
        language: str,
        latency_ms: float,
        success: bool,
        ontology_passed: bool,
        error_message: str | None = None,
    ) -> str:
        lang = _kb_language(language)
        emb_text = f"{task}\n---\n{result[:8000]}"

        embedder = LLMClient()
        er = await embedder.embed(emb_text)
        vec = list(er.embedding)
        if len(vec) != EMBED_DIM:
            raise ValueError(f"embedding 차원 불일치: 기대={EMBED_DIM}, 실제={len(vec)}")

        err = ""
        if not success:
            err = error_message or "실패"

        validation = await OntologyValidator.for_knowledge().validate(
            {
                "task": task[:500],
                "language": lang,
                "result": (result or "")[:10_000],
                "success": success,
                "error_message": err,
                "embedding": vec,
            },
        )
        if not validation.passed:
            raise ValueError(f"Knowledge Ontology 실패: {validation.summary}")

        row = AdkCodeExecution(
            task_id=task_id,
            task_text=task[:16000],
            language=lang,
            result_text=(result or "")[:16000],
            success=success,
            ontology_passed=ontology_passed,
            latency_ms=latency_ms,
            error_message=err or None,
            embedding=vec,
        )
        db.add(row)

        if not success and err:
            await self._bump_failure(db, task, err[:500])

        await db.flush()
        log.debug("knowledge 인덱싱 완료 id=%s", row.id[:8])
        return row.id

    async def _bump_failure(
        self,
        db: AsyncSession,
        task: str,
        err_snippet: str,
    ) -> None:
        sig = hashlib.sha256(
            f"{task[:200]}::{err_snippet[:120]}".encode(),
        ).hexdigest()[:48]
        existing = await db.scalar(
            select(AdkFailurePattern).where(AdkFailurePattern.signature == sig),
        )
        if existing:
            existing.occurrence_count = int(existing.occurrence_count) + 1
            existing.sample_task = task[:2000]
            existing.suggestion = (
                "프롬프트에 타입 제약과 예외 케이스를 명확히 하세요."
            )
            return
        db.add(
            AdkFailurePattern(
                signature=sig,
                occurrence_count=1,
                sample_task=task[:2000],
                suggestion="프롬프트 명확화·온톨로지 규칙 재검토",
            ),
        )

    async def find_similar(
        self,
        db: AsyncSession,
        task: str,
        top_k: int = 5,
        *,
        similarity_min: float = 0.8,
    ) -> list[dict[str, Any]]:
        embedder = LLMClient()
        er = await embedder.embed(task[:4000])
        vec = list(er.embedding)
        if len(vec) != EMBED_DIM:
            raise ValueError(f"embedding 차원 불일치: {len(vec)}")
        dist_expr = AdkCodeExecution.embedding.cosine_distance(vec)
        stmt = (
            select(AdkCodeExecution, dist_expr.label("dist"))
            .where(
                AdkCodeExecution.ontology_passed.is_(True),
                AdkCodeExecution.success.is_(True),
            )
            .order_by(dist_expr)
            .limit(max(top_k * 4, 8))
        )
        rows = (await db.execute(stmt)).all()

        ranked: list[dict[str, Any]] = []
        for ex, dist in rows:
            d = float(dist)
            score = max(0.0, min(1.0, 1.0 - d))
            if score < similarity_min:
                continue
            ranked.append(
                {
                    "id": ex.id,
                    "similarity": round(score, 4),
                    "task_text": ex.task_text[:320],
                    "result_text": (ex.result_text or "")[:800],
                    "language": ex.language,
                },
            )
            if len(ranked) >= top_k:
                break
        return ranked

    async def build_rag_context(
        self,
        db: AsyncSession,
        task: str,
        top_k: int = 3,
    ) -> str:
        sims = await self.find_similar(db, task, top_k=top_k, similarity_min=0.8)
        if not sims:
            return ""
        parts: list[str] = []
        for i, s in enumerate(sims, 1):
            parts.append(
                f"예시{i} (유사도 {s['similarity']}): 작업 요약 … {s['task_text']}\n"
                f"코드 스니펫 …\n{(s['result_text'] or '')[:600]}",
            )
        return "\n\n".join(parts)

    async def get_reuse_suggestion(
        self,
        db: AsyncSession,
        task: str,
    ) -> dict[str, Any]:
        dist_expr_sel = (
            await self._nearest_one(db, task)
        )
        if not dist_expr_sel:
            return {"action": "new", "reason": "유사 실행 이력 없음", "top_match": None}

        best, score = dist_expr_sel
        if score >= 0.95:
            tag = "reuse"
        elif score >= 0.8:
            tag = "reference"
        else:
            tag = "new"
        return {
            "action": tag,
            "top_similarity": score,
            "top_match": best,
        }

    async def _nearest_one(
        self,
        db: AsyncSession,
        task: str,
    ) -> tuple[dict[str, Any], float] | None:
        embedder = LLMClient()
        er = await embedder.embed(task[:4000])
        vec = list(er.embedding)
        if len(vec) != EMBED_DIM:
            raise ValueError(f"embedding 차원 불일치: {len(vec)}")
        dist_expr = AdkCodeExecution.embedding.cosine_distance(vec)
        stmt = (
            select(AdkCodeExecution, dist_expr.label("dist"))
            .where(
                AdkCodeExecution.ontology_passed.is_(True),
                AdkCodeExecution.success.is_(True),
            )
            .order_by(dist_expr)
            .limit(1)
        )
        row = (await db.execute(stmt)).first()
        if not row:
            return None
        ex, dist = row
        d = float(dist)
        score = max(0.0, min(1.0, 1.0 - d))
        payload = {
            "id": ex.id,
            "similarity": round(score, 4),
            "task_text": ex.task_text[:320],
            "result_text": (ex.result_text or "")[:800],
            "language": ex.language,
        }
        return payload, score

    async def get_failure_patterns(
        self,
        db: AsyncSession,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        stmt = (
            select(AdkFailurePattern)
            .order_by(AdkFailurePattern.occurrence_count.desc())
            .limit(limit)
        )
        rows = (await db.execute(stmt)).scalars().all()
        return [
            {
                "signature": r.signature,
                "occurrence_count": r.occurrence_count,
                "sample_task": (r.sample_task or "")[:200],
                "suggestion": r.suggestion,
            }
            for r in rows
        ]

    async def stats(self, db: AsyncSession) -> dict[str, Any]:
        q_total = await db.scalar(select(func.count()).select_from(AdkCodeExecution))
        q_pass = await db.scalar(
            select(func.count())
            .select_from(AdkCodeExecution)
            .where(
                AdkCodeExecution.ontology_passed.is_(True),
            ),
        )
        total = int(q_total or 0)
        passed = int(q_pass or 0)
        rate = (passed / total * 100.0) if total else 100.0
        return {
            "indexed_rows": total,
            "ontology_passed_rows": passed,
            "ontology_pass_rate_pct": round(rate, 2),
        }
