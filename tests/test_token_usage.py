from types import SimpleNamespace

from langchain_core.messages import AIMessage

from procurement_agent.db.models import init_db
from procurement_agent.middleware.token_usage import TokenUsageCallback
from procurement_agent.state.store import TaskStore


def make_store(tmp_path):
    store = TaskStore(init_db(tmp_path / "erp.db"))
    return store, store.create_task("x")


def llm_response(total_tokens: int):
    message = AIMessage(
        content="ok", usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": total_tokens}
    )
    return SimpleNamespace(generations=[[SimpleNamespace(message=message)]])


def test_records_real_usage(tmp_path):
    store, task_id = make_store(tmp_path)
    callback = TokenUsageCallback(store, task_id)
    callback.on_llm_end(llm_response(120))
    callback.on_llm_end(llm_response(80))

    usage = store.get_task(task_id).token_usage
    assert usage["total"] == 200
    assert usage["peak"] == 120
    assert callback.calls == 2


def test_ignores_missing_usage(tmp_path):
    store, task_id = make_store(tmp_path)
    callback = TokenUsageCallback(store, task_id)
    callback.on_llm_end(SimpleNamespace(generations=[[SimpleNamespace(message=AIMessage(content="x"))]]))

    assert store.get_task(task_id).token_usage.get("total", 0) == 0
    assert callback.calls == 0

