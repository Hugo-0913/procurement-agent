import pytest

from procurement_agent.agents.ordering import InsufficientQuotesError, run_ordering
from procurement_agent.agents.qualification import run_qualification
from procurement_agent.agents.sourcing import SourcingOutcome, run_sourcing
from procurement_agent.sandbox.policy import PolicyEngine
from procurement_agent.skills_loader import SkillRegistry

QUANTITY = 50
COST_CENTER = "CC-1001"


def prepare(env):
    qualified = run_qualification(env.repo, env.config, env.material.id)
    return run_sourcing(env.repo, env.config, env.material.id, QUANTITY, qualified)


def test_draft_total_matches_recommendation(env):
    sourcing = prepare(env)
    policy = PolicyEngine(env.config)
    draft, decision = run_ordering(
        env.repo, policy, sourcing, env.material.id, QUANTITY, COST_CENTER, "t-1"
    )
    assert draft.total_amount == pytest.approx(sourcing.recommended.total)
    assert draft.supplier_id == sourcing.recommended.supplier_id
    assert draft.cost_center == COST_CENTER
    assert decision.allowed is True


def test_no_approval_for_small_normal_order(env):
    sourcing = prepare(env)
    policy = PolicyEngine(env.config)
    _, decision = run_ordering(
        env.repo, policy, sourcing, env.material.id, QUANTITY, COST_CENTER, "t-1"
    )
    assert decision.requires_approval is False


def test_price_gap_computed(env):
    sourcing = prepare(env)
    cheapest = min(sourcing.comparisons, key=lambda item: item.total)
    expected = (sourcing.recommended.total - cheapest.total) / cheapest.total
    draft, _ = run_ordering(
        env.repo,
        PolicyEngine(env.config),
        sourcing,
        env.material.id,
        QUANTITY,
        COST_CENTER,
        "t-1",
    )
    assert draft.price_gap_ratio == pytest.approx(expected)
    assert draft.supplier_expiring_soon is False


def test_expiring_recommendation_flagged(env):
    sourcing = prepare(env)
    expiring = next(c for c in sourcing.comparisons if c.expiring_soon)
    forced = SourcingOutcome(
        comparisons=sourcing.comparisons,
        recommended=expiring,
        reason="forced",
    )
    draft, decision = run_ordering(
        env.repo,
        PolicyEngine(env.config),
        forced,
        env.material.id,
        QUANTITY,
        COST_CENTER,
        "t-1",
    )
    assert draft.supplier_expiring_soon is True
    assert decision.requires_approval is True
    assert any("临期" in rule for rule in decision.matched_rules)


def test_no_recommendation_raises(env):
    empty = SourcingOutcome(comparisons=[], recommended=None, insufficient_quotes=True)
    with pytest.raises(InsufficientQuotesError):
        run_ordering(
            env.repo,
            PolicyEngine(env.config),
            empty,
            env.material.id,
            QUANTITY,
            COST_CENTER,
            "t-1",
        )


def test_large_order_triggers_approval(env):
    sourcing = prepare(env)
    draft, decision = run_ordering(
        env.repo,
        PolicyEngine(env.config),
        sourcing,
        env.material.id,
        3000,
        COST_CENTER,
        "t-1",
    )
    assert draft.total_amount > env.config.approval_threshold
    assert decision.requires_approval is True


def test_skill_loaded_when_registry_passed(env):
    registry = SkillRegistry()
    sourcing = prepare(env)
    run_ordering(
        env.repo,
        PolicyEngine(env.config),
        sourcing,
        env.material.id,
        QUANTITY,
        COST_CENTER,
        "t-1",
        skills=registry,
    )
    assert registry.loaded_names == {"order_compliance"}

