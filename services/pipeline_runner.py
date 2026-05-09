"""Orchestrator PIPELINE — 코드 생성 + SOFTWARE Ontology 검증."""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.orchestrator import Orchestrator, OrchestraStrategy
from ontology.base import OntologyDomain

from models.software import CodeTask, TaskReview, TaskStatusEnum
from services.code_analyzer import CodeAnalyzer

log = logging.getLogger("services.pipeline_runner")


class PipelineRunner:
    """Planner→Generator→Reviewer→Fixer 파이프라인 (Week 4 스캐폴)."""

    def __init__(self) -> None:
        self._analyzer = CodeAnalyzer()

    async def run_inline(
        self,
        db: AsyncSession,
        description: str,
        language: str = "python",
    ) -> dict:
        """임시 CodeTask 를 만들고 동일 파이프라인 수행."""
        task = CodeTask(
            id=str(uuid.uuid4()),
            title=description[:120],
            description=description,
            language=language,
            status=TaskStatusEnum.PENDING,
        )
        db.add(task)
        await db.flush()
        return await self.run_task(db, task)

    async def run_task(self, db: AsyncSession, task: CodeTask) -> dict:
        task.status = TaskStatusEnum.RUNNING
        await db.flush()

        orch = Orchestrator(
            domain=OntologyDomain.SOFTWARE,
            strategy=OrchestraStrategy("pipeline"),
            max_iterations=2,
        )
        prompt = (
            f"{task.language} 로 다음 요구를 만족하는 **함수 하나**만 작성하세요. "
            f"설명: {task.description}\n"
            "코드만 출력하고 자연어 설명은 최소화하세요."
        )

        try:
            result       = await orch.execute(prompt)
            output       = (result.output or "").strip()
            iterations   = getattr(result, "iterations", 1)
            orch_passed  = getattr(result, "passed", False)

            vr = await self._analyzer.validate_snippet(output, task.language)
            on_pass = bool(vr.passed)

            task.output_code       = output[:16000] if output else None
            task.ontology_passed   = on_pass
            task.status            = TaskStatusEnum.COMPLETED

            fb = vr.summary
            if not vr.passed and vr.errors:
                fb = "; ".join(f"{e.code}:{e.message}" for e in vr.errors[:6])[:4000]

            review = TaskReview(
                id=str(uuid.uuid4()),
                task_id=task.id,
                passed=on_pass,
                feedback=fb,
                model_used="pipeline",
            )
            db.add(review)
            await db.flush()

            log.info(
                "pipeline 완료 task=%s orch_pass=%s onto=%s",
                task.id[:8],
                orch_passed,
                on_pass,
            )
            return {
                "task_id":           task.id,
                "status":            task.status.value,
                "output_code":       task.output_code,
                "ontology_passed":   on_pass,
                "iterations":        iterations,
                "summary":           vr.summary,
            }

        except Exception as e:
            log.exception("pipeline 실패")
            task.status = TaskStatusEnum.FAILED
            await db.flush()
            raise

    async def load_task(self, db: AsyncSession, task_id: str) -> CodeTask | None:
        return await db.scalar(select(CodeTask).where(CodeTask.id == task_id))
