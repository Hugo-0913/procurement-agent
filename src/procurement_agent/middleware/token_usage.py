"""采集真实 token 用量。

摘要中间件的估算值只能反映上下文规模，不能代表模型实际计费消耗。这里通过 LangChain
回调把每次模型调用的真实 ``usage_metadata`` 累加进任务记录，覆盖主 Agent 与子 Agent
的全部调用。离线模型没有 usage_metadata，此时不记录（不做假数据）。
"""

from __future__ import annotations

from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from procurement_agent.state.store import TaskStore


class TokenUsageCallback(BaseCallbackHandler):
    def __init__(self, store: TaskStore, task_id: str) -> None:
        super().__init__()
        self.store = store
        self.task_id = task_id
        self.total_tokens = 0
        self.calls = 0

    def record_message(self, message: Any) -> int:  # noqa: ANN401
        """记录单条模型返回消息的用量，返回本次 token 数（无用量时为 0）。"""
        usage = getattr(message, "usage_metadata", None) or {}
        total = int(usage.get("total_tokens") or 0)
        if total <= 0:
            return 0
        self.calls += 1
        self.total_tokens += total
        self.store.add_tokens(self.task_id, total, total=total)
        return total

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:  # noqa: ANN401
        for generation_list in getattr(response, "generations", []) or []:
            for generation in generation_list:
                self.record_message(getattr(generation, "message", None))
