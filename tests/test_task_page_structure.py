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

