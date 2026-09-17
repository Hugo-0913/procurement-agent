"""解析提示词渲染的回归测试。

历史缺陷：提示词里新增了 JSON 示例（含花括号），而渲染用的是 `str.format`，
导致花括号被当成格式化占位符，任务一提交就抛 `KeyError: '"items"'`。
这里固定住渲染行为，避免同类问题再次发生。
"""

from procurement_agent.agents.coordinator import build_parse_prompt


def test_prompt_renders_with_json_example_inside():
    prompt = build_parse_prompt("技能索引内容", "采购 50 箱 A4 纸和 20 个订书机")
    assert "采购 50 箱 A4 纸和 20 个订书机" in prompt
    assert "技能索引内容" in prompt
    # JSON 示例必须原样保留，不被格式化吞掉
    assert '{"items":[{"material_name"' in prompt.replace(" ", "")


def test_prompt_keeps_braces_for_multi_item_example():
    prompt = build_parse_prompt("idx", "x")
    assert prompt.count("{") >= 2
    assert "items" in prompt


def test_prompt_is_not_formatted_by_str_format():
    """确保实现没有退回 str.format：含花括号的提示词应可直接渲染。"""
    from procurement_agent.agents.coordinator import PARSE_PROMPT

    assert '"items"' in PARSE_PROMPT
    rendered = build_parse_prompt("idx", "需求")
    assert "{request_text}" not in rendered
    assert "{skill_index}" not in rendered
