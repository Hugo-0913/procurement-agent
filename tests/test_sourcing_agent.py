import pytest

from procurement_agent.agents.qualification import run_qualification
from procurement_agent.agents.sourcing import run_sourcing
from procurement_agent.erp.faults import SUPPLIER_C_NO_QUOTE
from procurement_agent.skills_loader import SkillRegistry

QUANTITY = 50


def prepare(env):
    qualified = run_qualification(env.repo, env.config, env.material.id)
    return run_sourcing(
        env.repo, env.config, env.material.id, QUANTITY, qualified
    )


def test_comparison_covers_all_qualified_quotes(env):
    outcome = prepare(env)
    assert {c.code for c in outcome.comparisons} == {"SUP-A", "SUP-B", "SUP-C"}
    sup_a = next(c for c in outcome.comparisons if c.code == "SUP-A")
    assert sup_a.total == pytest.approx(21.5 * QUANTITY)
    assert sup_a.history_avg is not None
    assert sup_a.deviation is not None


def test_recommendation_never_expiring(env):
    outcome = prepare(env)
    assert outcome.recommended is not None
    assert outcome.recommended.expiring_soon is False


def test_reason_explains_when_not_cheapest(env):
    outcome = prepare(env)
    cheapest = min(outcome.comparisons, key=lambda item: item.total)
    assert outcome.recommended.supplier_id != cheapest.supplier_id
    assert outcome.reason
    assert "临期" in outcome.reason
    assert "推荐" in outcome.reason


def test_insufficient_quotes_flagged(env):
    env.faults.set(SUPPLIER_C_NO_QUOTE, True)
    outcome = prepare(env)
    assert len(outcome.comparisons) == 2
    assert outcome.insufficient_quotes is False


def test_insufficient_quotes_true_when_below_threshold(env):
    from procurement_agent.config import ProcurementConfig

    env.faults.set(SUPPLIER_C_NO_QUOTE, True)
    strict = ProcurementConfig(50000.0, 3, 12000, 3, 30)
    qualified = run_qualification(env.repo, strict, env.material.id)
    outcome = run_sourcing(env.repo, strict, env.material.id, QUANTITY, qualified)
    assert outcome.insufficient_quotes is True


def test_skill_loaded_when_registry_passed(env):
    registry = SkillRegistry()
    qualified = run_qualification(env.repo, env.config, env.material.id)
    run_sourcing(
        env.repo, env.config, env.material.id, QUANTITY, qualified, skills=registry
    )
    assert registry.loaded_names == {"price_comparison"}

