from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_AGENTS_CONFIG_PATH = Path("config/agents.yaml")
REQUIRED_FIELDS = ("name", "role", "system_prompt", "tools", "skills")


@dataclass(frozen=True)
class AgentSpec:
    name: str
    role: str
    system_prompt: str
    tools: tuple[str, ...]
    skills: tuple[str, ...]
    max_tool_calls: int = 6


@dataclass(frozen=True)
class AgentsConfig:
    coordinator: AgentSpec
    subagents: dict[str, AgentSpec]

    def subagent_names(self) -> tuple[str, ...]:
        return tuple(spec.name for spec in self.subagents.values())


def _build_spec(raw: dict, owner: str) -> AgentSpec:
    if not isinstance(raw, dict):
        raise ValueError(f"Agent 配置格式错误: {owner}")
    missing = [field for field in REQUIRED_FIELDS if field not in raw]
    if missing:
        raise ValueError(f"Agent {owner} 缺少必需字段: {', '.join(missing)}")
    max_tool_calls = raw.get("max_tool_calls", 6)
    if not isinstance(max_tool_calls, int) or max_tool_calls <= 0:
        raise ValueError(f"Agent {owner} 的 max_tool_calls 必须为正整数")
    return AgentSpec(
        name=str(raw["name"]),
        role=str(raw["role"]),
        system_prompt=str(raw["system_prompt"]).strip(),
        tools=tuple(raw["tools"]),
        skills=tuple(raw["skills"]),
        max_tool_calls=max_tool_calls,
    )


def load_agents_config(path: Path | None = None) -> AgentsConfig:
    target = Path(path) if path is not None else DEFAULT_AGENTS_CONFIG_PATH
    raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    if "coordinator" not in raw:
        raise ValueError("agents.yaml 缺少 coordinator 配置")
    subagents_raw = raw.get("subagents") or {}
    if not isinstance(subagents_raw, dict) or not subagents_raw:
        raise ValueError("agents.yaml 缺少 subagents 配置")
    coordinator = _build_spec(raw["coordinator"], "coordinator")
    subagents = {
        key: _build_spec(value, f"subagents.{key}") for key, value in subagents_raw.items()
    }
    return AgentsConfig(coordinator=coordinator, subagents=subagents)

