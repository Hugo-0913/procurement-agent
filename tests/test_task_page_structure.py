"""执行页的结构约束。

历史缺陷：待办卡片（澄清 / 审批）原本插在 `#timeline` 里，而时间线每 5 秒整体重绘
`innerHTML`，卡片连同用户正在输入的内容一起被抹掉——表现为"澄清框输不进字"。

这里把结构钉住：待办卡片必须有独立容器，且时间线渲染不得碰它。
"""

from pathlib import Path

TPL = Path("src/procurement_agent/web/templates/task.html")
STATIC = Path("src/procurement_agent/web/static")


def test_action_cards_container_exists_outside_timeline():
    html = TPL.read_text(encoding="utf-8")
    assert 'id="action-cards"' in html
    # 卡片容器必须在时间线之前，且与时间线是兄弟节点，不能嵌在里面
    cards_at = html.index('id="action-cards"')
    timeline_at = html.index('id="timeline"')
    assert cards_at < timeline_at
    assert "</div>" in html[cards_at:timeline_at]


def test_cards_are_not_prepended_into_timeline():
    for name in ("task.js", "approval.js"):
        source = (STATIC / name).read_text(encoding="utf-8")
        assert 'getElementById("timeline").prepend' not in source, f"{name} 又把卡片塞回时间线了"
        assert 'getElementById("action-cards")' in source, f"{name} 未使用独立卡片容器"


def test_timeline_rerender_does_not_touch_action_cards():
    source = (STATIC / "timeline.js").read_text(encoding="utf-8")
    render_body = source[source.index("function renderTimeline"):]
    assert "action-cards" not in render_body, "时间线重绘不应涉及待办卡片容器"


def test_timeline_defaults_to_key_events_only():
    """时间线默认只显示关键事件，工具调用/技能加载/记忆读写默认折叠。

    页面要服务业务人员："发生了什么"必须一眼看到，"怎么做到的"按需展开。
    """
    html = TPL.read_text(encoding="utf-8")
    assert 'id="tl-key"' in html and 'id="tl-all"' in html
    assert 'class="seg-btn active" type="button">关键事件' in html, "默认视图应是关键事件"

    source = (STATIC / "timeline.js").read_text(encoding="utf-8")
    assert 'let timelineScope = "key"' in source, "时间线默认作用域必须是关键事件"
    key_block = source[source.index("KEY_EVENT_TYPES = new Set(["):]
    key_block = key_block[: key_block.index("])")]
    for event_type in ("stage_change", "agent_delegation", "approval_decided", "retry", "error"):
        assert event_type in key_block, f"{event_type} 属于关键事件，不应被默认折叠"
    for event_type in ("tool_call", "tool_result", "skill_loaded", "memory_written"):
        assert event_type not in key_block, f"{event_type} 是工程细节，应默认折叠"


def test_memory_and_skill_details_are_folded_by_default():
    """记忆全文与技能状态收进 <details>：默认收起，避免抢占业务信息的位置。"""
    html = TPL.read_text(encoding="utf-8")
    assert 'id="memory-summary"' in html
    for target in ('id="memory-block"', 'id="skill-status"'):
        at = html.index(target)
        details_at = html.rindex("<details", 0, at)
        assert "</details>" not in html[details_at:at], f"{target} 必须包在折叠区里"
        open_tag = html[details_at : html.index(">", details_at)]
        assert "open" not in open_tag, f"{target} 所在的折叠区不应默认展开"


def test_elapsed_time_stops_after_task_finishes():
    """任务结束后耗时停在 finished_at 上，不能再跟着墙钟一直涨。

    曾经只用 Date.now() - created_at 计算，完成的任务会显示"已耗时 84761s"并持续增加。
    """
    source = (STATIC / "task.js").read_text(encoding="utf-8")
    assert "function elapsedInfo(" in source, "耗时应集中在一个可测的函数里"
    assert "detail.finished_at" in source, "耗时必须读完成时间"
    assert "TERMINAL_STATES" in source and "detail.updated_at" in source, (
        "终态但缺 finished_at 的历史记录也要停住"
    )
    assert "Date.now() - Date.parse(detail.created_at)" not in source, (
        "不得只按当前时间计算耗时"
    )
    assert 'elapsed.finished ? "总耗时" : "已耗时"' in source, "结束后应改称总耗时"
