from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

FENCE_PATTERN = re.compile(r"^```[a-zA-Z0-9_-]*\s*|\s*```$")


def response_text(response: Any) -> str:
    """把模型返回值统一成纯文本。

    真实模型（如 ChatDeepSeek）返回 ``AIMessage``，内容可能是字符串或内容块列表；
    测试替身则直接返回字符串。这里统一处理，并顺带剥离 ```json 代码块包裹——
    真实模型很常见地会给 JSON 加上围栏，不剥离会导致结构化校验直接失败。
    """
    if isinstance(response, Mapping):
        content = response.get("content", response)
    else:
        content = getattr(response, "content", response)
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                parts.append(str(block.get("text", "")))
            else:
                parts.append(str(block))
        content = "".join(parts)
    text = str(content).strip()
    if text.startswith("```"):
        text = FENCE_PATTERN.sub("", text)
    return text.strip()
