from __future__ import annotations

import json

import pytest

from procurement_agent.agents.config import load_agents_config
from procurement_agent.agents.coordinator import CoordinatorDeps, build_handlers
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
DEFAULT_REQUEST = "采购 50 箱 一次性无菌注射器，下周一前到货，成本中心 CC-1001"


def parse_response(quantity: int = 50) -> str:
    return json.dumps(
        {
            "material_name": "一次性无菌注射器",
            "quantity": quantity,
            "unit": "箱",
            "expected_date": None,
            "budget": None,
            "cost_center": "CC-1001",
            "note": None,
        },
        ensure_ascii=False,
    )


def build_runner(
    tmp_path,
    responses: list[str],
    request_text: str = DEFAULT_REQUEST,
    delegate: bool = True,
):
    engine = init_db(tmp_path / "erp.db")
    seed_demo_data(engine)
    repo = ErpRepository(engine, FaultRegistry(engine))
    store = TaskStore(engine)
    skills = SkillRegistry()
    factory = FixedModelFactory(responses, agent_mode=True)
    factory.model.delegate = delegate
    deps = CoordinatorDeps(
        repo=repo,
        store=store,
        config=CONFIG,
        agents_config=load_agents_config(),
        skills=skills,
        policy=PolicyEngine(CONFIG),
        model_factory=factory,
    )
    graph = build_stage_graph(store, build_handlers(deps), CONFIG)
    runner = TaskRunner(store, graph)
    return repo, store, skills, runner


def event_types(store, task_id):
    return [e.event_type for e in store.list_events(task_id)]


def test_full_run_completes_with_expected_events(tmp_path):
    repo, store, _, runner = build_runner(tmp_path, [parse_response()])
    task_id = runner.start(DEFAULT_REQUEST)

    assert store.get_task(task_id).state is TaskState.COMPLETED
    kinds = event_types(store, task_id)
    for expected in ("stage_change", "agent_delegation", "tool_call", "tool_result", "skill_loaded"):
        assert expected in kinds
    assert repo.count_orders() == 1


def test_three_delegations_cover_all_subagents(tmp_path):
    _, store, _, runner = build_runner(tmp_path, [parse_response()])
    task_id = runner.start(DEFAULT_REQUEST)

    delegations = [
        e for e in store.list_events(task_id) if e.event_type == "agent_delegation"
    ]
    assert len(delegations) == 3
    assert {e.payload["to"] for e in delegations} == {
        "qualification_agent",
        "sourcing_agent",
        "ordering_agent",
    }


def test_skills_loaded_progressively_in_stage_order(tmp_path):
    _, store, _, runner = build_runner(tmp_path, [parse_response()])
    task_id = runner.start(DEFAULT_REQUEST)

    loaded = [
        e.payload["skill"] for e in store.list_events(task_id) if e.event_type == "skill_loaded"
    ]
    assert loaded == [
        "requirement_parsing",
        "supplier_qualification",
        "price_comparison",
        "order_compliance",
    ]


def test_clarification_task_never_loads_later_skills(tmp_path):
    _, store, skills, runner = build_runner(tmp_path, [parse_response(quantity=0)])
    task_id = runner.start("帮我再采购一些注射器")

    record = store.get_task(task_id)
    assert record.state is TaskState.AWAITING_CLARIFICATION
    assert skills.loaded_names == {"requirement_parsing"}
    delegations = [
        e for e in store.list_events(task_id) if e.event_type == "agent_delegation"
    ]
    assert delegations == []
    requested = [
        e for e in store.list_events(task_id) if e.event_type == "clarification_requested"
    ]
    assert requested and "数量" in requested[0].payload["question"]


def test_clarification_answer_continues_the_task(tmp_path):
    """用户补充信息后任务应从解析阶段续跑，而不是永远停在提问状态。"""
    _, store, _, runner = build_runner(
        tmp_path, [parse_response(quantity=0), parse_response(quantity=50)]
    )
    task_id = runner.start("帮我再采购一些注射器")
    assert store.get_task(task_id).state is TaskState.AWAITING_CLARIFICATION

    runner.continue_after_clarification(task_id, "50 箱")
    record = store.get_task(task_id)
    assert record.state is TaskState.COMPLETED
    assert record.structured_request["quantity"] == 50
    kinds = [e.event_type for e in store.list_events(task_id)]
    assert "clarification_answered" in kinds
    assert kinds.count("clarification_requested") == 1


def test_clarification_cannot_be_answered_for_other_states(tmp_path):
    from procurement_agent.state.store import InvalidTransition

    _, store, _, runner = build_runner(tmp_path, [parse_response()])
    task_id = runner.start(DEFAULT_REQUEST)
    assert store.get_task(task_id).state is TaskState.COMPLETED
    with pytest.raises(InvalidTransition):
        runner.continue_after_clarification(task_id, "50 箱")


def test_large_order_requests_approval(tmp_path):
    _, store, _, runner = build_runner(tmp_path, [parse_response(quantity=3000)])
    task_id = runner.start("采购 3000 箱 一次性无菌注射器")

    record = store.get_task(task_id)
    assert record.state is TaskState.AWAITING_APPROVAL
    requested = [
        e for e in store.list_events(task_id) if e.event_type == "approval_requested"
    ]
    assert requested
    assert any("阈值" in rule for rule in requested[0].payload["matched_rules"])


def test_small_order_completes_without_approval(tmp_path):
    _, store, _, runner = build_runner(tmp_path, [parse_response()])
    task_id = runner.start(DEFAULT_REQUEST)

    kinds = event_types(store, task_id)
    assert "approval_requested" not in kinds
    assert store.get_task(task_id).human_interventions == 0


def test_order_persisted_with_recommended_supplier(tmp_path):
    repo, store, _, runner = build_runner(tmp_path, [parse_response()])
    task_id = runner.start(DEFAULT_REQUEST)

    orders = repo.list_orders()
    assert len(orders) == 1
    order = orders[0]
    assert order.task_id == task_id
    # 注射器的推荐供应商是瑞康医械供应链（单价 62.5 + 运费 120）
    assert order.total_amount == pytest.approx(62.5 * 50 + 120)
    assert order.status == "CREATED"


def test_structured_request_saved(tmp_path):
    _, store, _, runner = build_runner(tmp_path, [parse_response()])
    task_id = runner.start(DEFAULT_REQUEST)

    record = store.get_task(task_id)
    assert record.structured_request["material_name"] == "一次性无菌注射器"
    assert record.structured_request["quantity"] == 50


def test_delegation_goes_through_framework(tmp_path):
    """三个子 Agent 都必须通过框架的 task 工具被委派，而不是状态机直接调用。"""
    _, store, _, runner = build_runner(tmp_path, [parse_response()])
    task_id = runner.start(DEFAULT_REQUEST)

    results = [
        e for e in store.list_events(task_id) if e.event_type == "delegation_result"
    ]
    assert len(results) == 3
    assert {e.payload["mode"] for e in results} == {"framework"}
    assert {e.payload["to"] for e in results} == {
        "qualification_agent",
        "sourcing_agent",
        "ordering_agent",
    }


def test_fallback_when_model_refuses_to_delegate(tmp_path):
    """模型不调用 task 工具时降级为直接执行，并在事件里如实标注 fallback。"""
    _, store, _, runner = build_runner(tmp_path, [parse_response()], delegate=False)
    task_id = runner.start(DEFAULT_REQUEST)

    assert store.get_task(task_id).state is TaskState.COMPLETED
    results = [
        e for e in store.list_events(task_id) if e.event_type == "delegation_result"
    ]
    assert len(results) == 3
    assert {e.payload["mode"] for e in results} == {"fallback"}
    assert all("reason" in e.payload for e in results)


def test_each_task_records_its_own_skill_events(tmp_path):
    """技能加载状态按任务记录：第二个任务不能因为进程内已加载过就漏发事件。"""
    _, store, _, runner = build_runner(tmp_path, [parse_response(), parse_response()])
    first = runner.start(DEFAULT_REQUEST)
    second = runner.start(DEFAULT_REQUEST)

    def loaded(task_id):
        return [
            e.payload["skill"]
            for e in store.list_events(task_id)
            if e.event_type == "skill_loaded"
        ]

    assert loaded(first) == loaded(second)
    assert loaded(second) == [
        "requirement_parsing",
        "supplier_qualification",
        "price_comparison",
        "order_compliance",
    ]


def test_invalid_json_from_model_marks_task_failed(tmp_path):
    """模型持续返回非法 JSON：按可重试错误重试，耗尽后任务失败并保留重试记录。"""
    _, store, _, runner = build_runner(tmp_path, ["这不是 JSON"] * 5)
    task_id = runner.start(DEFAULT_REQUEST)

    record = store.get_task(task_id)
    assert record.state is TaskState.FAILED
    errors = [e for e in store.list_events(task_id) if e.event_type == "error"]
    assert errors and errors[0].payload["error"] == "RetryExhausted"
    retries = [e for e in store.list_events(task_id) if e.event_type == "retry"]
    assert len(retries) == CONFIG.retry_max_attempts - 1
    assert all(e.payload["reason"] == "JSONDecodeError" for e in retries)
