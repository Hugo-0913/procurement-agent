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
    assert len(repo.list_suppliers()) == 4


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
