from __future__ import annotations

import json
from typing import Any

DEFAULT_PARSE_RESPONSE = json.dumps(
    {
        "material_name": "A4 纸",
        "quantity": 50,
        "unit": "箱",
        "expected_date": None,
        "budget": None,
        "cost_center": "CC-1001",
        "note": None,
    },
    ensure_ascii=False,
)


class OfflineModel:
    """离线演示模型：不联网，按固定脚本作答。"""

    def __init__(self, default_response: str = DEFAULT_PARSE_RESPONSE) -> None:
        self.default_response = default_response
        self.calls: list[Any] = []

    def invoke(self, messages: Any, **kwargs: Any) -> str:
        self.calls.append(messages)
        return self.default_response


def offline_model_factory(default_response: str | None = None):
    """返回一个可调用的模型工厂，签名与 build_chat_model 兼容。"""

    response = default_response or DEFAULT_PARSE_RESPONSE

    def factory(**overrides: Any) -> OfflineModel:
        return OfflineModel(response)

    return factory
