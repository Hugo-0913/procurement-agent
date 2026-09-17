from pathlib import Path

import pytest

from procurement_agent.agents.config import load_agents_config


def test_loads_coordinator_and_three_subagents():
    config = load_agents_config()
    assert config.coordinator.name == "coordinator"
    assert set(config.subagents) == {"qualification", "sourcing", "ordering"}
    assert config.subagent_names() == (
        "qualification_agent",
        "sourcing_agent",
        "ordering_agent",
    )


def test_every_declared_skill_exists_on_disk():
    config = load_agents_config()
    skills_root = Path("skills")
    specs = [config.coordinator, *config.subagents.values()]
    for spec in specs:
        for skill in spec.skills:
            assert (skills_root / skill / "SKILL.md").exists(), f"{spec.name} 引用了不存在的技能 {skill}"


def test_max_tool_calls_positive():
    config = load_agents_config()
    specs = [config.coordinator, *config.subagents.values()]
    assert all(spec.max_tool_calls > 0 for spec in specs)


def test_missing_field_reports_agent_name(tmp_path):
    bad = tmp_path / "agents.yaml"
    bad.write_text(
        "coordinator:\n"
        "  name: coordinator\n"
        "  role: 协调者\n"
        "subagents:\n"
        "  qualification:\n"
        "    name: q\n"
        "    role: r\n"
        "    system_prompt: p\n"
        "    tools: []\n"
        "    skills: []\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="coordinator"):
        load_agents_config(bad)


def test_missing_subagents_rejected(tmp_path):
    bad = tmp_path / "agents.yaml"
    bad.write_text(
        "coordinator:\n"
        "  name: c\n"
        "  role: r\n"
        "  system_prompt: p\n"
        "  tools: []\n"
        "  skills: []\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="subagents"):
        load_agents_config(bad)

