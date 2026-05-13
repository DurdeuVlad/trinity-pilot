"""Tests for ObjectiveBudget primitive (AC-4.1, AC-4.2, AC-4.3)."""
import pytest
from trinity_pilot.orchestrator.budget import BudgetExceeded, ObjectiveBudget


def test_charge_step_raises_after_max():
    budget = ObjectiveBudget(max_steps=3, max_tokens=1000, wall_seconds=60.0)
    budget.charge_step()
    budget.charge_step()
    budget.charge_step()
    with pytest.raises(BudgetExceeded) as exc_info:
        budget.charge_step()
    assert exc_info.value.budget_type == "steps"


def test_charge_step_does_not_raise_at_exactly_max():
    """Raises on > max_steps, not >= max_steps."""
    budget = ObjectiveBudget(max_steps=3, max_tokens=1000, wall_seconds=60.0)
    for _ in range(3):
        budget.charge_step()  # should not raise


def test_charge_tokens_raises_after_max():
    budget = ObjectiveBudget(max_steps=100, max_tokens=500, wall_seconds=60.0)
    budget.charge_tokens(500)
    with pytest.raises(BudgetExceeded) as exc_info:
        budget.charge_tokens(1)
    assert exc_info.value.budget_type == "tokens"


def test_charge_tokens_does_not_raise_at_exactly_max():
    budget = ObjectiveBudget(max_steps=100, max_tokens=500, wall_seconds=60.0)
    budget.charge_tokens(500)  # should not raise


def test_budget_exceeded_type_steps():
    budget = ObjectiveBudget(max_steps=1, max_tokens=10000, wall_seconds=60.0)
    budget.charge_step()
    with pytest.raises(BudgetExceeded) as exc_info:
        budget.charge_step()
    assert exc_info.value.budget_type == "steps"


def test_budget_exceeded_type_tokens():
    budget = ObjectiveBudget(max_steps=100, max_tokens=10, wall_seconds=60.0)
    budget.charge_tokens(10)
    with pytest.raises(BudgetExceeded) as exc_info:
        budget.charge_tokens(1)
    assert exc_info.value.budget_type == "tokens"


def test_steps_used_counter():
    budget = ObjectiveBudget(max_steps=100, max_tokens=10000, wall_seconds=60.0)
    budget.charge_step()
    budget.charge_step()
    assert budget.steps_used() == 2


def test_tokens_used_counter():
    budget = ObjectiveBudget(max_steps=100, max_tokens=10000, wall_seconds=60.0)
    budget.charge_tokens(30)
    budget.charge_tokens(70)
    assert budget.tokens_used() == 100


def test_wall_clock_budget_raises():
    budget = ObjectiveBudget(max_steps=100, max_tokens=10000, wall_seconds=0.0)
    with pytest.raises(BudgetExceeded) as exc_info:
        budget.charge_step()
    assert exc_info.value.budget_type == "wall_clock"


def test_default_returns_sensible_values():
    budget = ObjectiveBudget.default()
    assert budget.max_steps == 50
    assert budget.max_tokens == 100_000
    assert budget.wall_seconds == 600.0


def test_re_export_from_types():
    from trinity_pilot.core.types import ObjectiveBudget, BudgetExceeded  # noqa: F401
    assert ObjectiveBudget is not None
    assert BudgetExceeded is not None
