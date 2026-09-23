from pathlib import Path

from procurement_agent.config import ProcurementConfig
from procurement_agent.db.models import init_db
from procurement_agent.state.graph import TaskRunner, build_stage_graph
from procurement_agent.state.models import TaskState
from procurement_agent.state.nodes import StageResult
from procurement_agent.state.store import TaskStore

CONFIG = ProcurementConfig(50000.0, 3, 12000, 2, 30)


def make_handlers(total_amount: float, needs_approval: bool):
    def factory(stage: TaskState):
        def handler(task_id: str, payload: dict) -> StageResult:
            return StageResult(
                state=stage,
                payload={
                    "total_amount": total_amount,
                    "needs_approval": needs_approval,
                    "matched_rules": ["订单金额超阈值"] if needs_approval else [],
                },
            )

        return handler

    return {
        stage: factory(stage)
        for stage in (
            TaskState.PARSING,
            TaskState.QUALIFYING,
            TaskState.SOURCING,
            TaskState.ORDER_DRAFTING,
            TaskState.ORDERED,
        )
    }


def make_runner(db: Path, total: float, needs_approval: bool):
    store = TaskStore(init_db(db))
    graph = build_stage_graph(store, make_handlers(total, needs_approval), CONFIG)
    return store, TaskRunner(store, graph)


def test_happy_path_completes(tmp_path):
    store, runner = make_runner(tmp_path / "erp.db", 1000.0, False)
    task_id = runner.start("采购 50 箱 A4 纸")
    record = store.get_task(task_id)
    assert record.state is TaskState.COMPLETED
    assert record.finished_at is not None
    stages = [e.payload["to"] for e in store.list_events(task_id) if e.event_type == "stage_change"]
    assert stages == [
        "PARSING",
        "QUALIFYING",
        "SOURCING",
        "ORDER_DRAFTING",
        "ORDERED",
        "COMPLETED",
    ]


def test_approval_pauses_task(tmp_path):
    store, runner = make_runner(tmp_path / "erp.db", 62000.0, True)
    task_id = runner.start("采购 50 箱 A4 纸")
    assert store.get_task(task_id).state is TaskState.AWAITING_APPROVAL
    events = store.list_events(task_id)
    assert any(e.event_type == "approval_requested" for e in events)
    assert not any(e.event_type == "task_finished" for e in events)


def test_resume_after_process_restart(tmp_path):
    db = tmp_path / "erp.db"
    store, runner = make_runner(db, 62000.0, True)
    task_id = runner.start("采购 50 箱 A4 纸")
    assert store.get_task(task_id).state is TaskState.AWAITING_APPROVAL

    store2, runner2 = make_runner(db, 62000.0, True)
    runner2.resume(task_id, decision="approve", operator="alice", reason="预算内")
    record = store2.get_task(task_id)
    assert record.state is TaskState.COMPLETED
    assert record.human_interventions == 1
    decided = [e for e in store2.list_events(task_id) if e.event_type == "approval_decided"]
    assert decided and decided[0].payload["operator"] == "alice"
    assert decided[0].payload["reason"] == "预算内"

    # 审批留痕必须同时落到 approvals 表，而不只是事件流
    records = store2.list_approvals(task_id)
    assert len(records) == 1
    assert records[0]["decision"] == "approve"
    assert records[0]["operator"] == "alice"
    assert records[0]["reason"] == "预算内"
    assert records[0]["matched_rules"]


def test_reject_routes_back_to_sourcing(tmp_path):
    db = tmp_path / "erp.db"
    store, runner = make_runner(db, 62000.0, True)
    task_id = runner.start("采购 50 箱 A4 纸")

    store2, runner2 = make_runner(db, 1000.0, False)
    runner2.resume(task_id, decision="reject", operator="bob", reason="价格不合理")
    record = store2.get_task(task_id)
    assert record.state is TaskState.COMPLETED
    stages = [e.payload["to"] for e in store2.list_events(task_id) if e.event_type == "stage_change"]
    assert "REVISION_REQUIRED" in stages
    assert stages.count("SOURCING") == 2
