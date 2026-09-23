from pathlib import Path

import pytest

from procurement_agent.db.models import init_db
from procurement_agent.state.models import TaskState
from procurement_agent.state.store import InvalidTransition, TaskStore


def make_store(tmp_path: Path) -> TaskStore:
    return TaskStore(init_db(tmp_path / "erp.db"))


def test_create_task_starts_pending(tmp_path):
    store = make_store(tmp_path)
    task_id = store.create_task("采购 50 箱 一次性无菌注射器")
    record = store.get_task(task_id)
    assert record.state is TaskState.PENDING
    assert record.finished_at is None
    assert record.human_interventions == 0


def test_legal_transition(tmp_path):
    store = make_store(tmp_path)
    task_id = store.create_task("x")
    store.transition(task_id, TaskState.PARSING)
    assert store.get_task(task_id).state is TaskState.PARSING


def test_illegal_transition_raises(tmp_path):
    store = make_store(tmp_path)
    task_id = store.create_task("x")
    with pytest.raises(InvalidTransition) as exc:
        store.transition(task_id, TaskState.ORDERED)
    assert exc.value.from_state is TaskState.PENDING
    assert exc.value.to_state is TaskState.ORDERED
    assert store.get_task(task_id).state is TaskState.PENDING


def test_events_are_sequenced(tmp_path):
    store = make_store(tmp_path)
    task_id = store.create_task("x")
    first = store.append_event(task_id, "coordinator", "stage_change", {"to": "PARSING"})
    second = store.append_event(task_id, "coordinator", "tool_call", {"tool": "x"})
    assert (first.seq, second.seq) == (1, 2)
    assert [e.seq for e in store.list_events(task_id, after_seq=1)] == [1, 2][1:]


def test_transition_writes_stage_change_event(tmp_path):
    store = make_store(tmp_path)
    task_id = store.create_task("x")
    store.transition(task_id, TaskState.PARSING)
    events = store.list_events(task_id)
    assert len(events) == 1
    assert events[0].event_type == "stage_change"
    assert events[0].payload == {"from": "PENDING", "to": "PARSING"}


def test_finish_sets_finished_at(tmp_path):
    store = make_store(tmp_path)
    task_id = store.create_task("x")
    store.transition(task_id, TaskState.FAILED)
    store.finish_task(task_id, TaskState.FAILED)
    record = store.get_task(task_id)
    assert record.finished_at is not None
    assert record.state is TaskState.FAILED


def test_record_intervention_and_tokens(tmp_path):
    store = make_store(tmp_path)
    task_id = store.create_task("x")
    store.record_intervention(task_id)
    store.record_intervention(task_id)
    store.add_tokens(task_id, 120, total=900)
    store.add_tokens(task_id, 30, total=400)
    record = store.get_task(task_id)
    assert record.human_interventions == 2
    assert record.token_usage["total"] == 150
    assert record.token_usage["peak"] == 900


def test_list_tasks_filters_by_state(tmp_path):
    store = make_store(tmp_path)
    first = store.create_task("a")
    store.create_task("b")
    store.transition(first, TaskState.PARSING)
    assert [t.id for t in store.list_tasks(TaskState.PARSING)] == [first]
    assert len(store.list_tasks()) == 2


def test_set_structured_request(tmp_path):
    store = make_store(tmp_path)
    task_id = store.create_task("x")
    store.set_structured_request(task_id, {"quantity": 50, "material": "一次性无菌注射器"})
    assert store.get_task(task_id).structured_request == {
        "quantity": 50,
        "material": "一次性无菌注射器",
    }

