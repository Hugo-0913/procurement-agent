from procurement_agent.config import ProcurementConfig
from procurement_agent.db.models import init_db
from procurement_agent.memory.store import MemoryStore

CONFIG = ProcurementConfig(50000.0, 3, 12000, 2, 30)


def make_store(tmp_path) -> MemoryStore:
    return MemoryStore(init_db(tmp_path / "erp.db"), CONFIG)


def test_defaults_on_empty_db(tmp_path):
    store = make_store(tmp_path)
    prefs = store.preferences()
    assert prefs["prefer_tier"] == "A"
    assert prefs["default_cost_center"] == "CC-1001"
    assert prefs["approval_threshold"] == 50000.0


def test_set_preference_persists(tmp_path):
    store = make_store(tmp_path)
    store.set_preference("prefer_tier", "B")
    assert store.preferences()["prefer_tier"] == "B"


def test_supplier_stats_empty(tmp_path):
    store = make_store(tmp_path)
    stats = store.supplier_stats("SUP-A")
    assert stats["order_count"] == 0
    assert stats["last_unit_price"] is None


def test_record_order_outcome_accumulates(tmp_path):
    store = make_store(tmp_path)
    store.record_order_outcome("SUP-A", "ST-A4-500", 21.0, approved=True)
    store.record_order_outcome("SUP-A", "ST-A4-500", 23.0, approved=False)
    stats = store.supplier_stats("SUP-A")
    assert stats["order_count"] == 2
    assert stats["last_unit_price"] == 23.0
    assert stats["avg_unit_price"] == 22.0
    assert stats["approved_count"] == 1


def test_render_prompt_block_contains_preferences(tmp_path):
    store = make_store(tmp_path)
    store.record_order_outcome("SUP-A", "ST-A4-500", 21.8, approved=True)
    block = store.render_prompt_block()
    assert "已加载采购偏好" in block
    assert "50000" in block
    assert "SUP-A" in block
    assert "历史均价 ¥21.80" in block
    # 不应把完整历史明细塞进提示词
    assert "last_sku" not in block


def test_memory_survives_new_store_instance(tmp_path):
    db = tmp_path / "erp.db"
    engine = init_db(db)
    MemoryStore(engine, CONFIG).record_order_outcome("SUP-B", "ST-A4-500", 19.8, True)
    reopened = MemoryStore(init_db(db), CONFIG)
    assert reopened.supplier_stats("SUP-B")["order_count"] == 1

