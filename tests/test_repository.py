from pathlib import Path

from procurement_agent.db.models import init_db, seed_demo_data
from procurement_agent.erp.repository import ErpRepository


def make_repo(tmp_path: Path) -> ErpRepository:
    engine = init_db(tmp_path / "erp.db")
    seed_demo_data(engine)
    return ErpRepository(engine)


def test_find_material_by_name(tmp_path):
    repo = make_repo(tmp_path)
    material = repo.find_material_by_name("A4 纸")
    assert material is not None
    assert material.sku == "ST-A4-500"


def test_seed_is_idempotent(tmp_path):
    engine = init_db(tmp_path / "erp.db")
    seed_demo_data(engine)
    seed_demo_data(engine)
    repo = ErpRepository(engine)
    assert len(repo.list_suppliers()) == 4


def test_quotes_available_for_material(tmp_path):
    repo = make_repo(tmp_path)
    material = repo.find_material_by_name("A4 纸")
    quotes = repo.list_quotes(material.id)
    assert len(quotes) >= 3
    assert all(q.unit_price > 0 for q in quotes)


def test_price_history_available(tmp_path):
    repo = make_repo(tmp_path)
    material = repo.find_material_by_name("A4 纸")
    supplier = repo.supplier_by_code("SUP-A")
    history = repo.price_history(material.id, supplier.id)
    assert len(history) == 3
    assert 21.0 <= sum(history) / len(history) <= 22.0


def test_create_and_read_order(tmp_path):
    repo = make_repo(tmp_path)
    supplier = repo.supplier_by_code("SUP-A")
    material = repo.find_material_by_name("A4 纸")
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
    delta = (quals[0].expires_at - date.today()).days
    assert 0 < delta <= 30

