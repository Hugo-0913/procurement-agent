from __future__ import annotations

import json
from typing import Any


class FakeModel:
    """按脚本返回内容的模型替身，脚本耗尽立即报错，防止测试意外触网。"""

    def __init__(self, responses: list[str] | None = None) -> None:
        self.responses = list(responses or [])
        self.calls: list[Any] = []

    def invoke(self, messages: Any, **kwargs: Any) -> str:
        self.calls.append(messages)
        if not self.responses:
            raise AssertionError("FakeModel 脚本已耗尽")
        return self.responses.pop(0)


class FixedModelFactory:
    """可调用的模型工厂，签名与 build_chat_model 兼容。"""

    def __init__(self, responses: list[str] | None = None) -> None:
        self.model = FakeModel(responses)

    def __call__(self, **overrides: Any) -> FakeModel:
        return self.model

    def push(self, *responses: str) -> None:
        self.model.responses.extend(responses)


def json_response(**payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False)

