"""多物料采购：一次需求包含多种物料时，应逐项比价、多行下单、按合计金额判定审批。"""

from __future__ import annotations

import pytest

from procurement_agent.agents.config import load_agents_config
from procurement_agent.agents.coordinator import CoordinatorDeps, build_handlers
from procurement_agent.agents.ordering import OrderDraft
from procurement_agent.agents.payloads import (
    sourcing_items_from_payload,
    sourcing_items_to_payload,
)
from procurement_agent.agents.qualification import run_qualification
from procurement_agent.agents.sourcing import run_sourcing
from procurement_agent.config import ProcurementConfig
from procurement_agent.db.models import init_db, seed_demo_data
from procurement_agent.erp.faults import FaultRegistry
from procurement_agent.erp.repository import ErpRepository
from procurement_agent.sandbox.policy import PolicyEngine
from procurement_agent.skills_loader import SkillRegistry
from procurement_agent.state.graph import TaskRunner, build_stage_graph
from procurement_agent.state.models import TaskState
from procurement_agent.state.store import TaskStore
from tests.fakes import FixedModelFactory

CONFIG = ProcurementConfig(50000.0, 3, 12000, 2, 30)

MULTI_RESPONSE = """
{
  "items": [
    {"material_name": "一次性无菌注射器", "quantity": 50, "unit": "箱"},
    {"material_name": "医用外科口罩", "quantity": 20, "unit": "个"}
  ],
  "cost_center": "CC-1001",
  "expected_date": null
}
"""


def make_env(tmp_path):
    engine = init_db(tmp_path / "erp.db")
    seed_demo_data(engine)
    repo = ErpRepository(engine, FaultRegistry(engine))
    return repo, engine


def test_seed_has_two_materials(tmp_path):
    repo, _ = make_env(tmp_path)
    assert repo.find_material_by_name("一次性无菌注射器") is not None
    assert repo.find_material_by_name("医用外科口罩") is not None
    stapler = repo.find_material_by_name("医用外科口罩")
    assert len(repo.list_quotes(stapler.id)) == 3


def test_sourcing_payload_roundtrip_for_multiple_items(tmp_path):
    repo, _ = make_env(tmp_path)
    config = CONFIG
    qualified = run_qualification(repo, config, 1)
    results = []
    for sku, quantity in (("一次性无菌注射器", 50), ("医用外科口罩", 20)):
        material = repo.find_material_by_name(sku)
        outcome = run_sourcing(repo, config, material.id, quantity, qualified)
        results.append(
            {
                "material_id": material.id,
                "material_name": material.name,
                "quantity": quantity,
                "outcome": outcome,
            }
        )

    payload = sourcing_items_to_payload(results)
    assert len(payload["items"]) == 2
    restored = sourcing_items_from_payload(payload)
    assert len(restored) == 2
    assert all(outcome.recommended is not None for outcome in restored)


def test_policy_sums_lines_for_threshold():
    """多行订单按合计金额判定，而不是逐行比较。"""
    engine_config = ProcurementConfig(30000.0, 3, 12000, 2, 30)
    lines = [
        OrderDraft("t-1", 1, 1, 10, 2000.0, 20000.0, 3),
        OrderDraft("t-1", 2, 2, 10, 1500.0, 15000.0, 5),
    ]
    decision = PolicyEngine(engine_config).check_lines(lines)
    assert decision.requires_approval is True
    assert any("35000" in rule for rule in decision.matched_rules)


def test_policy_single_line_below_threshold_allows():
    engine_config = ProcurementConfig(30000.0, 3, 12000, 2, 30)
    lines = [OrderDraft("t-1", 1, 1, 10, 2000.0, 20000.0, 3)]
    assert PolicyEngine(engine_config).check_lines(lines).requires_approval is False


def test_multi_item_task_creates_one_order_per_item(tmp_path):
    engine = init_db(tmp_path / "erp.db")
    seed_demo_data(engine)
    repo = ErpRepository(engine, FaultRegistry(engine))
    store = TaskStore(engine)
    deps = CoordinatorDeps(
        repo=repo,
        store=store,
        config=CONFIG,
        agents_config=load_agents_config(),
        skills=SkillRegistry(),
        policy=PolicyEngine(CONFIG),
        model_factory=FixedModelFactory([MULTI_RESPONSE], agent_mode=True),
    )
    runner = TaskRunner(store, build_stage_graph(store, build_handlers(deps), CONFIG))
    task_id = runner.start("采购 50 箱 一次性无菌注射器和 20 盒医用外科口罩，成本中心 CC-1001")

    record = store.get_task(task_id)
    assert record.state is TaskState.COMPLETED
    assert len(record.structured_request["items"]) == 2

    orders = repo.list_orders()
    assert len(orders) == 2
    assert {order.material_id for order in orders} == {
        repo.find_material_by_name("一次性无菌注射器").id,
        repo.find_material_by_name("医用外科口罩").id,
    }
    assert sum(order.total_amount for order in orders) > 0


def test_multi_item_clarifies_when_one_item_unknown(tmp_path):
    engine = init_db(tmp_path / "erp.db")
    seed_demo_data(engine)
    repo = ErpRepository(engine, FaultRegistry(engine))
    store = TaskStore(engine)
    bad = """
    {"items": [
      {"material_name": "一次性无菌注射器", "quantity": 50},
      {"material_name": "呼吸机", "quantity": 1}
    ]}
    """
    deps = CoordinatorDeps(
        repo=repo,
        store=store,
        config=CONFIG,
        agents_config=load_agents_config(),
        skills=SkillRegistry(),
        policy=PolicyEngine(CONFIG),
        model_factory=FixedModelFactory([bad], agent_mode=True),
    )
    runner = TaskRunner(store, build_stage_graph(store, build_handlers(deps), CONFIG))
    task_id = runner.start("采购 50 箱 一次性无菌注射器和 1 台呼吸机")

    record = store.get_task(task_id)
    assert record.state is TaskState.AWAITING_CLARIFICATION
    requested = [
        e for e in store.list_events(task_id) if e.event_type == "clarification_requested"
    ]
    assert "呼吸机" in requested[0].payload["question"]
