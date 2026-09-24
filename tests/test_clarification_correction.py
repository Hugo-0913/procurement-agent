"""澄清补充必须是"修正"而不是"追加"。

历史缺陷：用户把"苹果"补充成"注射器"后，补充说明被追加到原文末尾，
原文里的"苹果"依然在，模型仍解析成苹果，任务卡在澄清状态无法纠正；
用户再补一次又追加一条，原文越来越乱。
"""

from procurement_agent.state.models import TaskState
from tests.test_coordinator import build_runner, parse_response


def test_latest_clarification_replaces_previous(tmp_path):
    _, store, _, runner = build_runner(
        tmp_path,
        [parse_response(quantity=0), parse_response(quantity=0), parse_response()],
    )
    task_id = runner.start("采购 50 箱苹果")
    assert store.get_task(task_id).state is TaskState.AWAITING_CLARIFICATION

    runner.continue_after_clarification(task_id, "注射器")
    assert store.get_task(task_id).state is TaskState.AWAITING_CLARIFICATION
    runner.continue_after_clarification(task_id, "一次性无菌注射器")

    text = store.get_task(task_id).request_text
    # 只保留最新一条补充说明，不累积
    assert text.count("补充说明：") == 1
    assert text.endswith("补充说明：一次性无菌注射器")
    assert text.startswith("采购 50 箱苹果")


def test_clarification_answer_is_marked_as_override(tmp_path):
    """解析提示词必须声明"补充说明优先于原文"，否则模型仍会取原文里的错误物料。"""
    from procurement_agent.agents.coordinator import build_parse_prompt

    prompt = build_parse_prompt("索引", "采购 50 箱苹果\n补充说明：注射器")
    assert "补充说明" in prompt
    assert "修正" in prompt or "为准" in prompt


def test_answered_event_kept_for_each_round(tmp_path):
    """事件流要保留每一轮澄清记录（审计需要），只有需求文本做覆盖。"""
    _, store, _, runner = build_runner(
        tmp_path,
        [parse_response(quantity=0), parse_response(quantity=0), parse_response()],
    )
    task_id = runner.start("采购 50 箱苹果")
    runner.continue_after_clarification(task_id, "注射器")
    runner.continue_after_clarification(task_id, "一次性无菌注射器")

    answered = [
        e for e in store.list_events(task_id) if e.event_type == "clarification_answered"
    ]
    assert [e.payload["answer"] for e in answered] == ["注射器", "一次性无菌注射器"]

