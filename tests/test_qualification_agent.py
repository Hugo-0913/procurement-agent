from procurement_agent.agents.qualification import run_qualification
from procurement_agent.erp.faults import SUPPLIER_B_EXPIRED
from procurement_agent.skills_loader import SkillRegistry


def test_blacklisted_supplier_rejected(env):
    outcome = run_qualification(env.repo, env.config, env.material.id)
    assert "SUP-D" not in {s.code for s in outcome.qualified}
    reasons = {r.code: r.reason for r in outcome.rejected}
    assert "黑名单" in reasons["SUP-D"]


def test_expired_supplier_rejected_when_fault_enabled(env):
    env.faults.set(SUPPLIER_B_EXPIRED, True)
    outcome = run_qualification(env.repo, env.config, env.material.id)
    assert "SUP-B" not in {s.code for s in outcome.qualified}
    reasons = {r.code: r.reason for r in outcome.rejected}
    assert "过期" in reasons["SUP-B"]


def test_expiring_soon_marked_not_rejected(env):
    outcome = run_qualification(env.repo, env.config, env.material.id)
    sup_c = next(s for s in outcome.qualified if s.code == "SUP-C")
    assert sup_c.expiring_soon is True
    assert any("临期" in note for note in outcome.notes)


def test_healthy_suppliers_all_qualified(env):
    outcome = run_qualification(env.repo, env.config, env.material.id)
    codes = {s.code for s in outcome.qualified}
    assert {"SUP-A", "SUP-B", "SUP-C"} <= codes


def test_skill_loaded_when_registry_passed(env):
    registry = SkillRegistry()
    run_qualification(env.repo, env.config, env.material.id, skills=registry)
    assert registry.loaded_names == {"supplier_qualification"}

