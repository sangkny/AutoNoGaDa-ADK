"""Phase 2 W5/W6 — Knowledge·Cost 회귀 (경량 DB 없음)."""
from __future__ import annotations

import pytest
from ontology.validator import OntologyValidator


@pytest.mark.asyncio(loop_scope="function")
@pytest.mark.parametrize(
    "payload,expects_pass",
    [
        (
            {
                "task": "테스트테스트더미패들길위한문장입니다",
                "language": "python",
                "result": "print(2)",
                "success": False,
                "error_message": "실패 근거",
                "embedding": [0.0] * 768,
            },
            True,
        ),
        (
            {
                "task": "짧음",
                "language": "python",
                "result": "bad",
                "success": False,
                "error_message": "x",
                "embedding": [0.0] * 700,
            },
            False,
        ),
    ],
)
async def test_knowledge_ontology(payload: dict, expects_pass: bool) -> None:
    vr = await OntologyValidator.for_knowledge().validate(payload)
    assert vr.passed is expects_pass


def test_complexity_and_cost_rates() -> None:
    from services.cost_optimizer import CostOptimizerService

    s = CostOptimizerService()
    assert s.analyze_complexity("환자 진료 기록 처리").value == "critical"
    assert s.analyze_complexity("tiny prompt").value == "simple"

    assert s.calculate_cost(1_000_000, "local") == 0.0
    assert s.calculate_cost(2_000_000, "openai") == pytest.approx(
        0.30,
        abs=1e-6,
    )


@pytest.mark.asyncio(loop_scope="function")
async def test_cost_escalates_critical() -> None:
    from services.cost_optimizer import CostOptimizerService

    s = CostOptimizerService()
    sel = await s.select_model("Medical patient security audit 필요")
    u = sel.selected_model.upper()
    assert "CONSENSUS" in sel.selected_model or "HEAVY" in u


@pytest.mark.asyncio(loop_scope="function")
async def test_cost_micro_budget_model() -> None:
    """예산 극소 + 복잡도 COMPLEX → COST-DEP-002 후 로컬 모델로 보정."""
    from services.cost_optimizer import CostOptimizerService, Complexity

    s = CostOptimizerService()
    long_task = ("장문 작업 명세입니다. 내용 채우기 " * 12).strip()
    assert s.analyze_complexity(long_task) == Complexity.COMPLEX

    sel = await s.select_model(long_task, budget_usd=0.004)
    m = sel.selected_model.lower()
    assert "local_fast" in m or "gemma-4-e4b" in m
