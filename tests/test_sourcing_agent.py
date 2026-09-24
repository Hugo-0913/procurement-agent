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
    # 黑名单供应商（SUP-D）即便有报价也不进入比价
    assert {c.code for c in outcome.comparisons} == {"SUP-A", "SUP-B", "SUP-C", "SUP-E"}
    sup_a = next(c for c in outcome.comparisons if c.code == "SUP-A")
    assert sup_a.total == pytest.approx(68.0 * QUANTITY)
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
    assert len(outcome.comparisons) == 3
    assert outcome.insufficient_quotes is False


def test_insufficient_quotes_true_when_below_threshold(env):
    from procurement_agent.config import ProcurementConfig

    env.faults.set(SUPPLIER_C_NO_QUOTE, True)
    strict = ProcurementConfig(50000.0, 3, 12000, 4, 30)
    qualified = run_qualification(env.repo, strict, env.material.id)
    outcome = run_sourcing(env.repo, strict, env.material.id, QUANTITY, qualified)
    assert outcome.insufficient_quotes is True


def test_tier_preference_applies_only_when_cost_is_close(env):
    """输液器 50 箱：瑞康（B 类）便宜 0.9%，落在 2% 容忍区间内，应改选 A 类的华康并说明理由。"""
    materials = {m.name: m for m in env.repo.list_materials()}
    infusion = materials["一次性使用输液器"]
    qualified = run_qualification(env.repo, env.config, infusion.id)
    outcome = run_sourcing(env.repo, env.config, infusion.id, 50, qualified)

    cheapest = min(outcome.comparisons, key=lambda item: item.total)
    assert cheapest.code == "SUP-B"
    assert outcome.recommended.code == "SUP-A"
    assert outcome.recommended.tier == "A"
    assert "采购偏好" in outcome.reason and "A 类" in outcome.reason


def test_tier_preference_does_not_beat_price(env):
    """注射器 2000 箱：瑞康（B 类）便宜 8.7%，超出容忍区间，偏好不得压过价格。"""
    qualified = run_qualification(env.repo, env.config, env.material.id)
    outcome = run_sourcing(env.repo, env.config, env.material.id, 2000, qualified)
    assert outcome.recommended.code == "SUP-B"
    assert "采购偏好" not in outcome.reason


def test_tier_preference_can_be_disabled(env):
    """容忍区间设为 0 时，等级偏好完全不生效，仍然选最低价。"""
    from procurement_agent.config import ProcurementConfig

    materials = {m.name: m for m in env.repo.list_materials()}
    infusion = materials["一次性使用输液器"]
    strict = ProcurementConfig(
        50000.0, 3, 12000, 2, 30, "approval", "A", 0.0
    )
    qualified = run_qualification(env.repo, strict, infusion.id)
    outcome = run_sourcing(env.repo, strict, infusion.id, 50, qualified)
    assert outcome.recommended.code == "SUP-B"


def test_skill_loaded_when_registry_passed(env):
    registry = SkillRegistry()
    qualified = run_qualification(env.repo, env.config, env.material.id)
    run_sourcing(
        env.repo, env.config, env.material.id, QUANTITY, qualified, skills=registry
    )
    assert registry.loaded_names == {"price_comparison"}


def test_lead_time_met_when_deadline_is_comfortable(env):
    from datetime import date, timedelta

    qualified = run_qualification(env.repo, env.config, env.material.id)
    deadline = (date.today() + timedelta(days=4)).isoformat()
    outcome = run_sourcing(
        env.repo, env.config, env.material.id, QUANTITY, qualified, expected_date=deadline
    )
    assert outcome.available_days == 4
    assert outcome.deadline_feasible is True
    assert outcome.recommended.on_time is True


def test_cheapest_excluded_when_lead_time_too_long(env):
    """最低价供应商交期不满足时，应改选能按时到货的供应商并说明原因。"""
    from datetime import date, timedelta

    qualified = run_qualification(env.repo, env.config, env.material.id)
    deadline = (date.today() + timedelta(days=3)).isoformat()
    outcome = run_sourcing(
        env.repo, env.config, env.material.id, QUANTITY, qualified, expected_date=deadline
    )
    fastest = min(outcome.comparisons, key=lambda item: item.lead_days)
    assert fastest.lead_days == 2
    # 交期 5 天的供应商被排除
    assert outcome.recommended.lead_days <= 3
    assert outcome.deadline_feasible is True


def test_infeasible_deadline_is_flagged(env):
    from datetime import date, timedelta

    qualified = run_qualification(env.repo, env.config, env.material.id)
    deadline = (date.today() + timedelta(days=1)).isoformat()
    outcome = run_sourcing(
        env.repo, env.config, env.material.id, QUANTITY, qualified, expected_date=deadline
    )
    assert outcome.deadline_feasible is False
    assert "交期" in outcome.reason
    assert "无法满足" in outcome.reason


def test_no_deadline_means_no_lead_time_check(env):
    outcome = prepare(env)
    assert outcome.available_days is None
    assert outcome.deadline_feasible is True
