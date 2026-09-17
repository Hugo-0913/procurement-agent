from __future__ import annotations

from typing import Any

from procurement_agent.sandbox.policy import PolicyDecision
from procurement_agent.state.store import TaskStore


class PolicyGuard:
    """把策略决策与事件流连接起来：被拦截的操作必须可观测。"""

    name = "policy_guard"

    def __init__(self, store: TaskStore) -> None:
        self.store = store

    def guard_tool_call(
        self,
        task_id: str,
        tool_name: str,
        args: dict[str, Any],
        decision: PolicyDecision,
    ) -> bool:
        if decision.allowed and not decision.requires_approval:
            return True
        self.store.append_event(
            task_id,
            agent=self.name,
            event_type="policy_denied",
            payload={
                "tool": tool_name,
                "args": args,
                "rules": list(decision.matched_rules),
                "reason": decision.reason or "策略拒绝",
                "requires_approval": decision.requires_approval,
            },
        )
        return False

