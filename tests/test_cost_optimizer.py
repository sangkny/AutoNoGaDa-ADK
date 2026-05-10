"""Phase 2 W6 — CostOptimizer 세부 테스트."""
from __future__ import annotations

import pytest


def test_medical_critical_keyword_detected_ko() -> None:
    from services.cost_optimizer import CostOptimizerService, Complexity

    s = CostOptimizerService()
    assert s.analyze_complexity("의료 규제 준수 함수") == Complexity.CRITICAL


@pytest.mark.asyncio(loop_scope="function")
async def test_select_model_always_returns_selection() -> None:
    from services.cost_optimizer import CostOptimizerService

    s = CostOptimizerService()
    out = await s.select_model(
        ("이 작업은 " + "내용 채우기 " * 20).strip(),
    )
    assert out.complexity in {"simple", "medium", "complex", "critical"}
    assert isinstance(out.estimated_tokens, int)
    assert out.estimated_tokens > 0


def test_budget_warning_helper() -> None:
    from services.cost_optimizer import CostOptimizerService

    s = CostOptimizerService()
    assert "80%" in s.budget_warning_for_rate(0.81)
    assert s.budget_warning_for_rate(0.2) == ""
