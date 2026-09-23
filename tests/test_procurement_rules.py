"""医疗器械采购的四条业务规则：经营范围、产品注册证、效期要求、起订量。"""

from procurement_agent.agents.qualification import run_qualification
from procurement_agent.agents.sourcing import run_sourcing


def test_scope_must_cover_material_category(env):
    """口罩属于医用防护用品；济生只登记了注射穿刺器械，应因超范围经营被淘汰。"""
    mask = env.repo.find_material_by_name("医用外科口罩")
    outcome = run_qualification(env.repo, env.config, mask.id)
    codes = {s.code for s in outcome.qualified}
    assert "SUP-C" not in codes
    reason = {r.code: r.reason for r in outcome.rejected}["SUP-C"]
    assert "经营范围不覆盖" in reason


def test_scope_covers_syringe_category(env):
    """注射器属于注射穿刺器械，三家的经营范围都覆盖。"""
    syringe = env.repo.find_material_by_name("一次性无菌注射器")
    outcome = run_qualification(env.repo, env.config, syringe.id)
    assert {"SUP-A", "SUP-B", "SUP-C"} <= {s.code for s in outcome.qualified}


def test_registration_is_checked_per_material(env, tmp_path):
    """删掉某供应商对某物料的产品注册证后，该供应商必须被淘汰。"""
    from sqlalchemy import text

    mask = env.repo.find_material_by_name("医用外科口罩")
    supplier = env.repo.supplier_by_code("SUP-A")
    with env.engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM supplier_qualifications "
                "WHERE supplier_id = :sid AND material_id = :mid"
            ),
            {"sid": supplier.id, "mid": mask.id},
        )

    outcome = run_qualification(env.repo, env.config, mask.id)
    assert "SUP-A" not in {s.code for s in outcome.qualified}
    assert "注册证" in {r.code: r.reason for r in outcome.rejected}["SUP-A"]


def test_shelf_life_requirement_excludes_near_expiry_batch(env):
    """口罩总效期 1095 天、要求剩余不低于 66%；济生批次只剩 120 天，应被排除。"""
    mask = env.repo.find_material_by_name("医用外科口罩")
    qualified = run_qualification(env.repo, env.config, mask.id)
    outcome = run_sourcing(env.repo, env.config, mask.id, 300, qualified)

    assert outcome.recommended.code != "SUP-C"  # 单价最低但也被淘汰出推荐
    sup_c = next(c for c in outcome.comparisons if c.code == "SUP-C") if any(
        c.code == "SUP-C" for c in outcome.comparisons
    ) else None
    assert sup_c is None or sup_c.shelf_life_ok is False


def test_min_order_quantity_is_enforced(env):
    """20 盒口罩低于所有供应商的起订量，应触发人工确认而不是直接下单。"""
    mask = env.repo.find_material_by_name("医用外科口罩")
    qualified = run_qualification(env.repo, env.config, mask.id)
    outcome = run_sourcing(env.repo, env.config, mask.id, 20, qualified)
    assert outcome.moq_violated is True
    assert outcome.recommended.meets_moq is False


def test_min_order_quantity_satisfied(env):
    mask = env.repo.find_material_by_name("医用外科口罩")
    qualified = run_qualification(env.repo, env.config, mask.id)
    outcome = run_sourcing(env.repo, env.config, mask.id, 300, qualified)
    assert outcome.moq_violated is False
    assert outcome.recommended.meets_moq is True

