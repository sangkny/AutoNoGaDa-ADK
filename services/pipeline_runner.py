"""Orchestrator PIPELINE — 코드 생성·리뷰·수정 (SOFTWARE 도메인)."""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.fixer import FixerAgent
from agents.orchestrator import Orchestrator, OrchestraStrategy
from agents.reviewer import ReviewResult, ReviewerAgent
from ontology.base import OntologyDomain, ValidationError

from events import EVENT_CODE_GENERATED, publish_platform_event
from config import get_settings
from models.software import CodeTask, TaskReview, TaskStatusEnum
from services.code_analyzer import CodeAnalyzer
from services.git_service import GitOperationError, GitService, commit_result_as_dict
from services.pipeline_monitor import get_pipeline_monitor

log = logging.getLogger("services.pipeline_runner")


class PipelineRunner:
    """생성(generate) · 리뷰(review) · 수정(fix)."""

    def __init__(self) -> None:
        self._analyzer = CodeAnalyzer()

    async def run_inline(
        self,
        db: AsyncSession,
        description: str,
        language: str = "python",
    ) -> dict[str, Any]:
        """임시 CodeTask 를 만들고 PIPELINE 실행."""
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

    async def run_task(self, db: AsyncSession, task: CodeTask) -> dict[str, Any]:
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

        mon = get_pipeline_monitor()
        t0 = time.perf_counter()
        try:
            await mon.track(
                task.id, "pipeline", "PipelineRunner", "running",
                {"language": task.language, "phase_detail": "enqueue"},
            )
            await mon.track(
                task.id, "plan", "Planner", "running",
                {"_progress_hint": 15},
            )
            await mon.track(task.id, "plan", "Planner", "completed", {})
            await mon.track(
                task.id, "generate", "Generator", "running",
                {"_progress_hint": 30},
            )

            result       = await orch.execute(prompt)
            output       = (result.output or "").strip()
            iterations   = getattr(result, "iterations", 1)
            orch_passed  = getattr(result, "passed", False)

            await mon.track(
                task.id,
                "generate",
                "Generator",
                "completed",
                {"orchestrator_passed": orch_passed, "ralf_iterations": iterations},
            )
            await mon.track(
                task.id, "review", "Reviewer", "running",
                {"_progress_hint": 72, "iteration": iterations},
            )
            await mon.track(
                task.id, "review", "Reviewer", "completed",
                {},
            )
            if iterations > 1:
                await mon.track(
                    task.id, "fix", "Fixer", "running",
                    {"_progress_hint": 82, "loops": iterations - 1},
                )
                await mon.track(
                    task.id, "fix", "Fixer", "completed",
                    {"ralf_iterations": iterations},
                )

            await mon.track(
                task.id, "ontology", "OntologyValidator", "running",
                {"_progress_hint": 90},
            )

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

            quality_report = self._quality_report(vr, orch_passed)

            log.info(
                "pipeline 완료 task=%s orch_pass=%s onto=%s",
                task.id[:8],
                orch_passed,
                on_pass,
            )
            redis_url = (get_settings().redis_url or "").strip()
            if redis_url:
                try:
                    await publish_platform_event(
                        redis_url,
                        EVENT_CODE_GENERATED,
                        {
                            "task_id":         task.id,
                            "language":        task.language,
                            "ontology_passed": on_pass,
                            "quality_report":  quality_report,
                        },
                    )
                except Exception as e:
                    log.warning("Redis 이벤트 code.generated 발행 스킵: %s", e)

            lat_ms = (time.perf_counter() - t0) * 1000.0
            await mon.track(
                task.id, "ontology", "OntologyValidator",
                "completed" if on_pass else "failed",
                {"ontology_passed": on_pass},
            )
            await mon.record_completion(
                task.id,
                success=on_pass,
                latency_ms=lat_ms,
                iterations=iterations,
                ontology_passed=on_pass,
                rough_char_count=len(output or ""),
                model_hint="local/e4b-pipeline",
            )

            return {
                "task_id":           task.id,
                "status":            task.status.value,
                "output_code":       task.output_code,
                "ontology_passed":   on_pass,
                "iterations":        iterations,
                "summary":           vr.summary,
                "quality_report":    quality_report,
            }

        except Exception:
            log.exception("pipeline 실패")
            lat_ms = (time.perf_counter() - t0) * 1000.0
            try:
                await mon.track(
                    task.id, "pipeline", "PipelineRunner", "failed",
                    {"error": "exception"},
                )
                await mon.record_completion(
                    task.id,
                    success=False,
                    latency_ms=lat_ms,
                    iterations=0,
                    ontology_passed=False,
                    model_hint="local/e4b-pipeline",
                )
            except Exception:
                log.debug("monitor 실패 기록 스킵", exc_info=True)
            task.status = TaskStatusEnum.FAILED
            await db.flush()
            raise

    def _quality_report(self, vr: Any, orch_passed: bool) -> dict[str, Any]:
        errs = getattr(vr, "errors", None) or []
        out_errs: list[dict[str, str]] = []
        for e in errs[:20]:
            if isinstance(e, ValidationError):
                out_errs.append(
                    {
                        "code":    e.code,
                        "message": e.message,
                        "field":   getattr(e, "field", "") or "",
                    },
                )
            else:
                out_errs.append({"code": "?", "message": str(e), "field": ""})
        return {
            "ontology_passed":      bool(vr.passed),
            "ontology_summary":     vr.summary,
            "ontology_errors":      out_errs,
            "orchestrator_passed":  orch_passed,
        }

    async def generate(
        self,
        db: AsyncSession,
        task: str,
        language: str = "python",
        *,
        auto_commit: bool = False,
    ) -> dict[str, Any]:
        """
        POST /pipeline/generate — 함수 설명 기반 코드 생성 + 품질 리포트.

        ``auto_commit`` 이 True 이면 생성 코드를 저장소 내 ``generated/snippets/`` 에
        쓴 뒤 `git add` + `git commit` 한다 (Week 5 5-1-1).
        """
        payload = await self.run_inline(db, task, language)
        if (
            auto_commit and payload.get("output_code") and payload.get("status") != "failed"
        ):
            await self._try_git_commit_after_generate(
                payload,
                natural_task=task,
                language=language,
            )
        return payload

    async def _try_git_commit_after_generate(
        self,
        payload: dict[str, Any],
        natural_task: str,
        language: str,
    ) -> None:
        settings = get_settings()
        svc    = GitService(settings)
        repo   = settings.git_repo_path
        tid    = str(payload.get("task_id", "unknown"))
        code   = str(payload.get("output_code") or "")
        try:
            rel = await svc.write_generated_snippet(repo, tid, code, language)
            msg = (
                f"feat(autonogada): codegen task={tid[:8]} — "
                f"{natural_task[:72]}"
            )
            res = await svc.commit(repo, msg, [rel])
            git_info = commit_result_as_dict(res)
            git_info["path"] = rel
            git_info["pr_description"] = GitService.create_pr_description(
                [
                    {
                        "path":   rel,
                        "status": "generated",
                        "summary": natural_task[:120],
                    },
                ],
            )
            payload["git"] = git_info
        except GitOperationError as e:
            log.warning("auto_commit 실패: %s", e)
            payload["git"] = {"committed": False, "error": str(e)}
        except OSError as e:
            log.warning("snippet 쓰기 실패: %s", e)
            payload["git"] = {"committed": False, "error": str(e)}

    async def review_code(
        self,
        code: str,
        language: str = "python",
        context: str | None = None,
    ) -> dict[str, Any]:
        """
        POST /pipeline/review — HEAVY ReviewerAgent 로 코드 리뷰.
        """
        reviewer = ReviewerAgent(domain=OntologyDomain.SOFTWARE)
        hint     = context or "제공된 코드의 품질·보안·파이썬 관례를 검토하세요."
        res      = await reviewer.run(
            hint,
            context={"generated": code, "iteration": 0},
        )
        if not res.success:
            return {
                "passed":         False,
                "feedback":       res.error or "reviewer 실패",
                "llm_review":     "",
                "ontology_passed": None,
                "ontology_summary": "",
            }

        review_out: ReviewResult = res.output
        vr_meta   = await self._analyzer.validate_snippet(code, language)
        return {
            "passed":            review_out.passed,
            "feedback":          review_out.feedback,
            "llm_review":        review_out.llm_review,
            "ontology_passed":   bool(vr_meta.passed),
            "ontology_summary":  vr_meta.summary,
        }

    async def fix_code(
        self,
        code: str,
        error_message: str,
        context: str | None = None,
    ) -> dict[str, Any]:
        """
        POST /pipeline/fix — FixerAgent 로 오류/피드백 기반 수정 코드 생성.
        """
        review_stub = ReviewResult(
            passed=False,
            feedback=error_message,
            ontology_result=None,
        )
        fixer = FixerAgent(domain=OntologyDomain.SOFTWARE)
        task  = context or "주어진 오류를 해결하도록 코드를 수정하세요."
        res   = await fixer.run(
            task,
            context={
                "generated": code,
                "review":    review_stub,
                "iteration": 1,
            },
        )
        if not res.success:
            return {"fixed_code": None, "error": res.error or "fixer 실패"}
        return {"fixed_code": str(res.output).strip(), "error": None}

    async def load_task(self, db: AsyncSession, task_id: str) -> CodeTask | None:
        return await db.scalar(select(CodeTask).where(CodeTask.id == task_id))
