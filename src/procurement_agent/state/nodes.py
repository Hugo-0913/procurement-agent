from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from procurement_agent.state.models import TaskState


@dataclass
class StageResult:
    """单个阶段处理器的返回结果。"""

    state: TaskState
    payload: dict[str, Any] = field(default_factory=dict)

