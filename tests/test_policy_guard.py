from procurement_agent.db.models import init_db
from procurement_agent.middleware.policy_guard import PolicyGuard
from procurement_agent.sandbox.policy import PolicyDecision
from procurement_agent.state.store import TaskStore


def make_guard(tmp_path):
    store = TaskStore(init_db(tmp_path / "erp.db"))
    task_id = store.create_task("采购 50 箱 A4 纸")
    return PolicyGuard(store), store, task_id


def test_allowed_decision_passes_without_event(tmp_path):
    guard, store, task_id = make_guard(tmp_path)
    allowed = guard.guard_tool_call(task_id, "order_create", {}, PolicyDecision(allowed=True))
    assert allowed is True
    assert store.list_events(task_id) == []


def test_approval_required_is_recorded(tmp_path):
    guard, store, task_id = make_guard(tmp_path)
    decision = PolicyDecision(
        allowed=True,
        requires_approval=True,
        matched_rules=("订单金额 ¥62400.00 > 阈值 ¥50000.00",),
        reason="订单金额超阈值",
    )
    allowed = guard.guard_tool_call(task_id, "order_create", {"qty": 50}, decision)
    assert allowed is False
    events = store.list_events(task_id)
    assert len(events) == 1
    assert events[0].event_type == "policy_denied"
    assert events[0].payload["tool"] == "order_create"
    assert events[0].payload["rules"] == ["订单金额 ¥62400.00 > 阈值 ¥50000.00"]
    assert events[0].payload["requires_approval"] is True


def test_denied_decision_is_recorded(tmp_path):
    guard, store, task_id = make_guard(tmp_path)
    decision = PolicyDecision(
        allowed=False,
        matched_rules=("命令 rm 在禁止清单中",),
        reason="命令 rm 在禁止清单中",
    )
    assert guard.guard_tool_call(task_id, "shell", {"argv": ["rm"]}, decision) is False
    assert store.list_events(task_id)[0].payload["requires_approval"] is False

