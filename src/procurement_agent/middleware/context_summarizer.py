from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Callable

from procurement_agent.config import ProcurementConfig

TRUNCATED_PREFIX = "[工具结果摘要]"
ESSENTIAL_PREFIX = "【保留的关键要素】"
SUMMARY_PREFIX = "【上下文摘要】"
SUMMARY_PROMPT = "请把以下对话压缩为不超过 3 行的中文摘要，保留结论与未决问题。"


def _is_cjk(char: str) -> bool:
    return "\u4e00" <= char <= "\u9fff" or "\u3000" <= char <= "\u303f"


def estimate_tokens(text: str) -> int:
    """粗略 token 估算：中文按 1 字 1 token，其余按 4 字符 1 token。"""
    if not text:
        return 0
    cjk = sum(1 for char in text if _is_cjk(char))
    others = len(text) - cjk
    return cjk + math.ceil(others / 4)


@dataclass(frozen=True)
class SummaryResult:
    before_tokens: int
    after_tokens: int
    dropped_categories: tuple[str, ...] = ()
    summary: str = ""


@dataclass
class ContextSummarizer:
    """上下文治理中间件：结构化保留关键要素，折叠工具返回原文。"""

    config: ProcurementConfig
    model_factory: Callable[..., Any] | None = None

    def estimate_messages(
        self, messages: list[dict[str, Any]], essential: dict[str, Any]
    ) -> int:
        total = estimate_tokens(json.dumps(essential, ensure_ascii=False)) if essential else 0
        for message in messages:
            total += estimate_tokens(str(message.get("content", "")))
        return total

    def _summarize(self, messages: list[dict[str, Any]]) -> str:
        if self.model_factory is None:
            return "（无模型可用，保留原始结论）"
        model = self.model_factory()
        payload = [
            {"role": "system", "content": SUMMARY_PROMPT},
            {
                "role": "user",
                "content": "\n".join(
                    f"{m.get('role')}: {str(m.get('content', ''))[:500]}" for m in messages
                ),
            },
        ]
        return str(model.invoke(payload))

    def maybe_summarize(
        self, messages: list[dict[str, Any]], essential: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], SummaryResult | None]:
        before = self.estimate_messages(messages, essential)
        if before < self.config.context_token_threshold:
            return messages, None

        dropped: list[str] = []
        compacted: list[dict[str, Any]] = []
        if essential:
            compacted.append(
                {
                    "role": "system",
                    "content": f"{ESSENTIAL_PREFIX}"
                    f"{json.dumps(essential, ensure_ascii=False)}",
                }
            )
        for message in messages:
            if message.get("role") == "tool":
                first_line = str(message.get("content", "")).strip().splitlines()
                head = first_line[0][:120] if first_line else ""
                compacted.append(
                    {"role": "tool", "content": f"{TRUNCATED_PREFIX} {head}"}
                )
                dropped.append("tool_result")
            else:
                compacted.append(message)

        summary = self._summarize(compacted)
        result_messages = [
            *compacted,
            {"role": "system", "content": f"{SUMMARY_PREFIX}{summary}"},
        ]
        after = self.estimate_messages(result_messages, essential)
        return result_messages, SummaryResult(
            before_tokens=before,
            after_tokens=after,
            dropped_categories=tuple(dict.fromkeys(dropped)),
            summary=summary,
        )

