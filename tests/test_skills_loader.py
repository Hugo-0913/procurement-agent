from pathlib import Path

import pytest

from procurement_agent.skills_loader import SkillNotFound, SkillRegistry

SKILLS_ROOT = Path("skills")
EXPECTED = {
    "requirement_parsing",
    "supplier_qualification",
    "price_comparison",
    "order_compliance",
}


def test_lists_four_skills_without_loading_bodies():
    registry = SkillRegistry(SKILLS_ROOT)
    metas = registry.list_metadata()
    assert {m.name for m in metas} == EXPECTED
    assert all(m.description for m in metas)
    assert registry.loaded_names == set()
    assert registry.metadata_only_names() == EXPECTED


def test_load_returns_body_and_marks_loaded():
    registry = SkillRegistry(SKILLS_ROOT)
    body = registry.load("price_comparison")
    assert "比价" in body
    assert registry.loaded_names == {"price_comparison"}
    assert "price_comparison" not in registry.metadata_only_names()


def test_unknown_skill_raises():
    registry = SkillRegistry(SKILLS_ROOT)
    with pytest.raises(SkillNotFound):
        registry.load("nope")


def test_reset_clears_loaded_state():
    registry = SkillRegistry(SKILLS_ROOT)
    registry.load("order_compliance")
    registry.reset()
    assert registry.loaded_names == set()


def test_render_index_contains_names_and_descriptions_only():
    registry = SkillRegistry(SKILLS_ROOT)
    index = registry.render_index()
    for name in EXPECTED:
        assert name in index
    # 索引里不应出现正文内容
    assert "常见错误" not in index
    assert "综合成本 = 单价" not in index


def test_missing_root_yields_empty_index(tmp_path):
    registry = SkillRegistry(tmp_path / "nowhere")
    assert registry.list_metadata() == []

