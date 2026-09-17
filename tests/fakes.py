"""测试替身。

直接复用 ``OfflineChatModel``（真正的 BaseChatModel），只把兜底行为换成脚本：
测试与生产走**同一条委派代码路径**，替身与真实对象的类型也保持一致——历史上正是
因为替身与真实模型返回类型不同，才导致缺陷只在真机暴露。
"""

from __future__ import annotations

import json
from typing import Any

from procurement_agent.agents.offline import OfflineChatModel


def FakeModel(
    responses: list[str] | None = None, *, agent_mode: bool = False
) -> OfflineChatModel:
    return OfflineChatModel(script=list(responses or []), agent_mode=agent_mode)


class FixedModelFactory:
    """可调用的模型工厂，签名与 build_chat_model 兼容，返回同一个模型实例。"""

    def __init__(
        self, responses: list[str] | None = None, *, agent_mode: bool = False
    ) -> None:
        self.model = FakeModel(responses, agent_mode=agent_mode)

    def __call__(self, **overrides: Any) -> OfflineChatModel:
        return self.model

    def push(self, *responses: str) -> None:
        assert self.model.script is not None
        self.model.script.extend(responses)


def json_response(**payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False)
