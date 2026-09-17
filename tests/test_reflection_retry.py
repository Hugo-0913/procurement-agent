import pytest

from procurement_agent.db.models import init_db
from procurement_agent.middleware.reflection_retry import (
    CORRECTIVE_ACTIONS,
    RetryExhausted,
    classify_error,
    run_with_retry,
)
from procurement_agent.state.store import TaskStore


def make_store(tmp_path):
    store = TaskStore(init_db(tmp_path / "erp.db"))
    return store, store.create_task("x")


def retry_events(store, task_id):
    return [e for e in store.list_events(task_id) if e.event_type == "retry"]


def test_retries_then_succeeds(tmp_path):
    store, task_id = make_store(tmp_path)
    calls = {"n": 0}

    def flaky(_attempt: int) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("报价接口超时")
        return "ok"

    result = run_with_retry(
        flaky, max_attempts=3, store=store, task_id=task_id, agent="sourcing_agent"
    )
    assert result == "ok"
    events = retry_events(store, task_id)
    assert len(events) == 1
    assert events[0].payload["attempt"] == 1
    assert events[0].payload["reason"] == "TimeoutError"
    assert events[0].payload["corrective_action"] == CORRECTIVE_ACTIONS["TimeoutError"]
    assert events[0].agent == "sourcing_agent"


def test_fatal_error_is_not_retried(tmp_path):
    store, task_id = make_store(tmp_path)
    with pytest.raises(ValueError):
        run_with_retry(
            lambda _attempt: (_ for _ in ()).throw(ValueError("参数缺失")),
            max_attempts=3,
            store=store,
            task_id=task_id,
            agent="sourcing_agent",
        )
    assert retry_events(store, task_id) == []


def test_exhausted_raises_with_attempt_count(tmp_path):
    store, task_id = make_store(tmp_path)
    with pytest.raises(RetryExhausted) as exc:
        run_with_retry(
            lambda _attempt: (_ for _ in ()).throw(ConnectionError("断连")),
            max_attempts=3,
            store=store,
            task_id=task_id,
            agent="sourcing_agent",
        )
    assert exc.value.attempts == 3
    assert isinstance(exc.value.last_error, ConnectionError)
    assert len(retry_events(store, task_id)) == 2


def test_classify_json_error_before_value_error():
    import json

    try:
        json.loads("nope")
    except json.JSONDecodeError as exc:
        assert classify_error(exc) == "retryable"
    assert classify_error(ValueError("x")) == "fatal"
    assert classify_error(TimeoutError()) == "retryable"


def test_classify_sdk_connection_errors_by_class_name():
    class APIConnectionError(Exception):
        pass

    class OpenAIConnectionSubclass(APIConnectionError):
        pass

    assert classify_error(APIConnectionError("x")) == "retryable"
    assert classify_error(OpenAIConnectionSubclass("x")) == "retryable"
    assert classify_error(RuntimeError("x")) == "fatal"


def test_sdk_error_retries_with_action(tmp_path):
    store, task_id = make_store(tmp_path)
    calls = {"n": 0}

    class APIConnectionError(Exception):
        pass

    def flaky(_attempt: int) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise APIConnectionError("Connection error.")
        return "ok"

    result = run_with_retry(
        flaky, max_attempts=3, store=store, task_id=task_id, agent="coordinator"
    )
    assert result == "ok"
    retries = retry_events(store, task_id)
    assert len(retries) == 1
    assert retries[0].payload["corrective_action"] == "等待 1 秒后重连模型接口"


def test_on_retry_callback_receives_event(tmp_path):
    store, task_id = make_store(tmp_path)
    seen = []
    calls = {"n": 0}

    def flaky(_attempt: int) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("断连")
        return "done"

    run_with_retry(
        flaky,
        max_attempts=3,
        store=store,
        task_id=task_id,
        agent="sourcing_agent",
        on_retry=seen.append,
    )
    assert len(seen) == 1
    assert seen[0].corrective_action == CORRECTIVE_ACTIONS["ConnectionError"]
