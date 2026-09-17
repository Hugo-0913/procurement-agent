from datetime import date
from pathlib import Path

from procurement_agent.db.models import init_db, seed_demo_data
from procurement_agent.erp.faults import (
    ALL_QUOTES_OVER_BUDGET,
    SUPPLIER_B_EXPIRED,
    SUPPLIER_C_NO_QUOTE,
    FaultRegistry,
)
from procurement_agent.erp.repository import ErpRepository


def make_repo(tmp_path: Path):
    engine = init_db(tmp_path / "erp.db")
    seed_demo_data(engine)
    faults = FaultRegistry(engine)
    return ErpRepository(engine, faults), faults


def test_supplier_b_qualification_becomes_expired(tmp_path):
    repo, faults = make_repo(tmp_path)
    supplier_b = repo.supplier_by_code("SUP-B")
    before = repo.list_qualifications(supplier_b.id)
    assert all(q.expires_at >= date.today() for q in before)

    faults.set(SUPPLIER_B_EXPIRED, True)
    after = repo.list_qualifications(supplier_b.id)
    assert any(q.expires_at < date.today() for q in after)


def test_supplier_c_quote_removed(tmp_path):
    repo, faults = make_repo(tmp_path)
    material = repo.find_material_by_name("A4 纸")
    before = len(repo.list_quotes(material.id))
    faults.set(SUPPLIER_C_NO_QUOTE, True)
    assert len(repo.list_quotes(material.id)) == before - 1


def test_all_quotes_over_budget_triples_price(tmp_path):
    repo, faults = make_repo(tmp_path)
    material = repo.find_material_by_name("A4 纸")
    before = {q.supplier_id: q.unit_price for q in repo.list_quotes(material.id)}
    faults.set(ALL_QUOTES_OVER_BUDGET, True)
    after = {q.supplier_id: q.unit_price for q in repo.list_quotes(material.id)}
    for supplier_id, price in before.items():
        assert round(after[supplier_id], 2) == round(price * 3.0, 2)


def test_fault_flags_persisted(tmp_path):
    _, faults = make_repo(tmp_path)
    faults.set(ALL_QUOTES_OVER_BUDGET, True)
    assert faults.is_enabled(ALL_QUOTES_OVER_BUDGET) is True
    assert faults.list_flags()[ALL_QUOTES_OVER_BUDGET] is True
    assert faults.list_flags()[SUPPLIER_B_EXPIRED] is False


def test_flag_can_be_turned_off(tmp_path):
    _, faults = make_repo(tmp_path)
    faults.set(SUPPLIER_C_NO_QUOTE, True)
    faults.set(SUPPLIER_C_NO_QUOTE, False)
    assert faults.is_enabled(SUPPLIER_C_NO_QUOTE) is False

