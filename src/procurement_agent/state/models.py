from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class TaskState(StrEnum):
    PENDING = "PENDING"
    PARSING = "PARSING"
    AWAITING_CLARIFICATION = "AWAITING_CLARIFICATION"
    QUALIFYING = "QUALIFYING"
    SOURCING = "SOURCING"
    ORDER_DRAFTING = "ORDER_DRAFTING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    ORDERED = "ORDERED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


TERMINAL_STATES = frozenset({TaskState.COMPLETED, TaskState.FAILED})

ALLOWED_TRANSITIONS: dict[TaskState, frozenset[TaskState]] = {
    TaskState.PENDING: frozenset({TaskState.PARSING, TaskState.FAILED}),
    TaskState.PARSING: frozenset(
        {
            TaskState.QUALIFYING,
            TaskState.AWAITING_CLARIFICATION,
            TaskState.FAILED,
        }
    ),
    TaskState.AWAITING_CLARIFICATION: frozenset({TaskState.PARSING, TaskState.FAILED}),
    TaskState.QUALIFYING: frozenset({TaskState.SOURCING, TaskState.FAILED}),
    TaskState.SOURCING: frozenset({TaskState.ORDER_DRAFTING, TaskState.FAILED}),
    TaskState.ORDER_DRAFTING: frozenset(
        {TaskState.AWAITING_APPROVAL, TaskState.ORDERED, TaskState.FAILED}
    ),
    TaskState.AWAITING_APPROVAL: frozenset(
        {
            TaskState.ORDERED,
            TaskState.REVISION_REQUIRED,
            TaskState.ORDER_DRAFTING,
            TaskState.FAILED,
        }
    ),
    TaskState.REVISION_REQUIRED: frozenset({TaskState.SOURCING, TaskState.FAILED}),
    TaskState.ORDERED: frozenset({TaskState.COMPLETED, TaskState.FAILED}),
    TaskState.COMPLETED: frozenset(),
    TaskState.FAILED: frozenset(),
}

EVENT_TYPES = frozenset(
    {
        "stage_change",
        "agent_delegation",
        "tool_call",
        "tool_result",
        "skill_loaded",
        "clarification_requested",
        "clarification_answered",
        "policy_denied",
        "retry",
        "context_summarized",
        "approval_requested",
        "approval_decided",
        "memory_loaded",
        "memory_written",
        "error",
        "task_finished",
    }
)

STAGE_LABELS: dict[TaskState, str] = {
    TaskState.PENDING: "待启动",
    TaskState.PARSING: "需求解析",
    TaskState.AWAITING_CLARIFICATION: "等待澄清",
    TaskState.QUALIFYING: "资质核验",
    TaskState.SOURCING: "比价分析",
    TaskState.ORDER_DRAFTING: "订单草稿",
    TaskState.AWAITING_APPROVAL: "订单审批",
    TaskState.REVISION_REQUIRED: "驳回重跑",
    TaskState.ORDERED: "订单生成",
    TaskState.COMPLETED: "完成",
    TaskState.FAILED: "失败",
}


@dataclass(frozen=True)
class TaskEvent:
    task_id: str
    seq: int
    agent: str
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""


@dataclass
class TaskRecord:
    id: str
    request_text: str
    state: TaskState
    structured_request: dict[str, Any] | None = None
    created_at: str = ""
    updated_at: str = ""
    finished_at: str | None = None
    human_interventions: int = 0
    token_usage: dict[str, Any] = field(default_factory=dict)
