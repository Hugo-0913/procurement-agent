from __future__ import annotations

import json
import re
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
    """离线演示模型：不联网。解析请求用规则解析器，压缩上下文用固定摘要。

    它替代的是"模型"这一环，不是业务规则：解析逻辑是正则，行为完全确定，
    因此评测结果可复现；同时它会真正读取输入文本，而不是返回写死的答案。
    """

    SUMMARY_HINT = "压缩"
    FIXED_SUMMARY = "已完成资质核验与比价，推荐 A 类供应商，等待下一步。"

    def __init__(self, default_response: str = DEFAULT_PARSE_RESPONSE) -> None:
        self.default_response = default_response
        self.calls: list[Any] = []

    def invoke(self, messages: Any, **kwargs: Any) -> str:
        self.calls.append(messages)
        prompt = _flatten(messages)
        if self.SUMMARY_HINT in prompt:
            return self.FIXED_SUMMARY
        if self.default_response is not None:
            return self.default_response
        return json.dumps(
            parse_request_text(_extract_request(prompt)), ensure_ascii=False
        )


UNIT_PATTERN = re.compile(r"(\d+)\s*(箱|包|件|个|套|卷|支|盒|本)")
# 独立数字：排除"A4"这类字母数字混合标识中的数字，避免把物料型号当成数量
NUMBER_PATTERN = re.compile(r"(?<![A-Za-z0-9])(\d+)(?![A-Za-z0-9])")
COST_CENTER_PATTERN = re.compile(r"(CC-\d+)")
MATERIAL_HINTS = (("A4", "A4 纸"), ("纸", "A4 纸"))


def _flatten(messages: Any) -> str:
    if isinstance(messages, str):
        return messages
    if isinstance(messages, dict):
        return str(messages.get("content", ""))
    parts: list[str] = []
    for message in messages or []:
        if isinstance(message, dict):
            parts.append(str(message.get("content", "")))
        else:
            parts.append(str(message))
    return "\n".join(parts)


def _extract_request(prompt: str) -> str:
    marker = "采购需求："
    if marker in prompt:
        return prompt.split(marker, 1)[1].strip()
    return prompt


def parse_request_text(text: str) -> dict[str, Any]:
    """规则化需求解析：抽取数量、成本中心与物料名称，抽不到就返回 null。

    故意保持简单且不猜测：物料名称识别不出来时返回 null，由协调器向用户提问澄清。
    """
    unit_match = UNIT_PATTERN.search(text)
    quantity = int(unit_match.group(1)) if unit_match else None
    if quantity is None:
        number_match = NUMBER_PATTERN.search(text)
        quantity = int(number_match.group(1)) if number_match else None

    cost_center_match = COST_CENTER_PATTERN.search(text)
    material = next(
        (name for hint, name in MATERIAL_HINTS if hint in text), None
    )

    return {
        "material_name": material,
        "quantity": quantity,
        "unit": unit_match.group(2) if unit_match else None,
        "expected_date": None,
        "budget": None,
        "cost_center": cost_center_match.group(1) if cost_center_match else None,
        "note": None,
    }


def offline_model_factory(default_response: str | None = None):
    """返回可调用的模型工厂，签名与 build_chat_model 兼容。

    传入 ``default_response`` 时按固定脚本作答（测试用）；不传时使用规则解析器。
    """

    def factory(**overrides: Any) -> OfflineModel:
        return OfflineModel(default_response)

    return factory
