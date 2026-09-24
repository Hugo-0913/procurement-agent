from pathlib import Path

from procurement_agent.db.models import init_db, seed_demo_data
from procurement_agent.erp.repository import ErpRepository


def make_repo(tmp_path: Path) -> ErpRepository:
    engine = init_db(tmp_path / "erp.db")
    seed_demo_data(engine)
    return ErpRepository(engine)


def test_find_material_by_name(tmp_path):
    repo = make_repo(tmp_path)
    material = repo.find_material_by_name("一次性无菌注射器")
    assert material is not None
    assert material.sku == "ST-SYR-5ML"


def test_seed_is_idempotent(tmp_path):
    engine = init_db(tmp_path / "erp.db")
    seed_demo_data(engine)
    seed_demo_data(engine)
    repo = ErpRepository(engine)
    assert len(repo.list_suppliers()) == 5


def test_seed_covers_five_materials_by_four_usable_suppliers(tmp_path):
    """演示数据规模：5 种物料 × 4 家可用供应商的报价矩阵，另加 1 家黑名单供应商。"""
    engine = init_db(tmp_path / "erp.db")
    seed_demo_data(engine)
    repo = ErpRepository(engine)

    materials = repo.list_materials()
    assert [m.name for m in materials] == [
        "一次性无菌注射器",
        "一次性使用输液器",
        "医用外科口罩",
        "医用丁腈检查手套",
        "无菌纱布块",
    ]

    blacklisted = {s.code for s in repo.list_suppliers() if s.blacklisted}
    assert blacklisted == {"SUP-D"}
    for material in materials:
        suppliers = {
            repo.supplier(q.supplier_id).code for q in repo.list_quotes(material.id)
        }
        assert {"SUP-A", "SUP-B", "SUP-C", "SUP-E"} <= suppliers, (
            f"{material.name} 缺少可用供应商报价"
        )
        # 4 家可用 + 黑名单 1 家；黑名单的报价不会被比价采用，仅用于演示"报价最低也不可用"
        assert len(suppliers) == 5


def test_existing_db_gets_licence_backfilled(tmp_path):
    """老库缺少医疗器械经营许可证时，重跑种子应补齐，而不是被幂等逻辑跳过。"""
    import sqlite3

    db = tmp_path / "erp.db"
    engine = init_db(db)
    seed_demo_data(engine)
    # 模拟"早期建的库"：只保留营业执照，删掉经营许可证
    con = sqlite3.connect(db)
    con.execute(
        "DELETE FROM supplier_qualifications WHERE qual_type = '医疗器械经营许可证'"
    )
    con.commit()
    con.close()

    seed_demo_data(engine)  # 幂等路径，应触发回填
    repo = ErpRepository(engine)
    for supplier in repo.list_suppliers():
        types = {q.qual_type for q in repo.list_qualifications(supplier.id)}
        assert "医疗器械经营许可证" in types, f"{supplier.code} 未补齐经营许可证"


def test_existing_db_gets_new_materials_and_suppliers_backfilled(tmp_path):
    """老库（只有 2 种物料、4 家供应商）重跑种子后应补齐新物料、新供应商及其报价与资质。"""
    import sqlite3

    db = tmp_path / "erp.db"
    engine = init_db(db)
    seed_demo_data(engine)
    # 模拟"扩数据之前建的库"：删掉后加的物料、供应商与其报价
    con = sqlite3.connect(db)
    con.execute(
        "DELETE FROM quotes WHERE supplier_id IN (SELECT id FROM suppliers WHERE code = 'SUP-E')"
    )
    con.execute("DELETE FROM suppliers WHERE code = 'SUP-E'")
    con.execute(
        "DELETE FROM materials WHERE sku NOT IN ('ST-SYR-5ML', 'ST-MASK-50')"
    )
    con.commit()
    con.close()

    seed_demo_data(engine)  # 幂等路径，应触发补齐
    repo = ErpRepository(engine)

    assert len(repo.list_materials()) == 5
    supplier_e = repo.supplier_by_code("SUP-E")
    assert supplier_e is not None, "新供应商未补齐"
    types = {q.qual_type for q in repo.list_qualifications(supplier_e.id)}
    assert {"营业执照", "医疗器械经营许可证"} <= types

    gauze = repo.find_material_by_name("无菌纱布块")
    quotes = {repo.supplier(q.supplier_id).code for q in repo.list_quotes(gauze.id)}
    assert {"SUP-A", "SUP-B", "SUP-C", "SUP-E"} <= quotes
    # 补齐的报价要带完整字段，否则"起订量全是 1"会让规则静默失效
    sup_e_quote = next(
        q for q in repo.list_quotes(gauze.id) if q.supplier_id == supplier_e.id
    )
    assert sup_e_quote.min_order_qty == 50
    assert sup_e_quote.remaining_shelf_life_days == 900


def test_existing_db_gets_licence_scope_refreshed(tmp_path):
    """老库里存着旧经营范围的供应商，重跑种子后必须同步。

    只在"缺行"时补资质是不够的：改过经营范围的供应商会留着旧措辞，
    新增的物料类别被误判成"超范围经营"，表现是老库比新建库少一家可用供应商。
    """
    import sqlite3

    db = tmp_path / "erp.db"
    engine = init_db(db)
    seed_demo_data(engine)
    con = sqlite3.connect(db)
    con.execute(
        "UPDATE supplier_qualifications SET scope = '注射穿刺器械、医用防护用品' "
        "WHERE qual_type = '医疗器械经营许可证'"
    )
    con.commit()
    con.close()

    seed_demo_data(engine)
    repo = ErpRepository(engine)
    for code in ("SUP-A", "SUP-B", "SUP-E"):
        supplier = repo.supplier_by_code(code)
        scope = next(
            q.scope
            for q in repo.list_qualifications(supplier.id)
            if q.qual_type == "医疗器械经营许可证"
        )
        assert "医用敷料" in scope, f"{code} 的经营范围未同步"


def test_quotes_available_for_material(tmp_path):
    repo = make_repo(tmp_path)
    material = repo.find_material_by_name("一次性无菌注射器")
    quotes = repo.list_quotes(material.id)
    assert len(quotes) >= 3
    assert all(q.unit_price > 0 for q in quotes)


def test_price_history_available(tmp_path):
    repo = make_repo(tmp_path)
    material = repo.find_material_by_name("一次性无菌注射器")
    supplier = repo.supplier_by_code("SUP-A")
    history = repo.price_history(material.id, supplier.id)
    assert len(history) == 3
    assert 67.0 <= sum(history) / len(history) <= 69.0


def test_create_and_read_order(tmp_path):
    repo = make_repo(tmp_path)
    supplier = repo.supplier_by_code("SUP-A")
    material = repo.find_material_by_name("一次性无菌注射器")
    order_id = repo.create_order(
        {
            "task_id": "t-1",
            "supplier_id": supplier.id,
            "material_id": material.id,
            "quantity": 50,
            "unit_price": 21.5,
            "total_amount": 1075.0,
            "lead_days": 3,
            "cost_center": "CC-1001",
        }
    )
    order = repo.get_order(order_id)
    assert order.total_amount == 1075.0
    assert order.status == "CREATED"
    assert repo.count_orders() == 1
    assert len(repo.list_orders()) == 1


def test_blacklisted_supplier_present_in_master_data(tmp_path):
    repo = make_repo(tmp_path)
    suppliers = {s.code: s for s in repo.list_suppliers()}
    assert suppliers["SUP-D"].blacklisted is True
    assert suppliers["SUP-A"].tier == "A"


def test_qualification_expiry_relative_to_today(tmp_path):
    repo = make_repo(tmp_path)
    from datetime import date

    sup_c = repo.supplier_by_code("SUP-C")
    quals = repo.list_qualifications(sup_c.id)
    assert quals
    # 每家都有营业执照与医疗器械经营许可证，临期演示看的是许可证
    licence = next(q for q in quals if q.qual_type == "医疗器械经营许可证")
    delta = (licence.expires_at - date.today()).days
    assert 0 < delta <= 30
    business = next(q for q in quals if q.qual_type == "营业执照")
    assert (business.expires_at - date.today()).days > 365
