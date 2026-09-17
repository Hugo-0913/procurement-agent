from __future__ import annotations

import json
import re
from typing import Any, ClassVar, Sequence

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field
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


class OfflineChatModel(BaseChatModel):
    """离线演示模型：不联网。解析请求用规则解析器，压缩上下文用固定摘要。

    实现为真正的 ``BaseChatModel``，因此可以交给 DeepAgents 绑定工具、参与框架的
    Agent 循环——这样离线模式与真实模式走的是**同一条委派代码路径**，而不是两套实现。
    """

    SUMMARY_HINT: ClassVar[str] = "压缩"
    FIXED_SUMMARY: ClassVar[str] = "已完成资质核验与比价，推荐 A 类供应商，等待下一步。"
    MAIN_ROLE_HINT: ClassVar[str] = "采购协调者"
    ROLE_TOOL: ClassVar[dict[str, str]] = {
        "资质核验专员": "qualification_query",
        "比价分析专员": "quote_query",
        "订单执行专员": "order_draft",
    }
    SUBAGENT_KEYWORDS: ClassVar[dict[str, str]] = {
        "资质": "qualification_agent",
        "比价": "sourcing_agent",
        "订单": "ordering_agent",
    }

    default_response: str | None = None
    script: list[str] | None = None
    delegate: bool = True
    agent_mode: bool = False
    calls: list[Any] = Field(default_factory=list)
    bound_tools: list[str] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "procurement-offline-rule-model"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "OfflineChatModel":
        self.bound_tools = [
            getattr(tool, "name", getattr(tool, "__name__", str(tool))) for tool in tools
        ]
        return self

    def _reply(self, messages: list[BaseMessage]) -> AIMessage:
        prompt = _flatten(messages)

        # 非 Agent 模式：纯脚本作答，不做任何角色推断（供只关心返回内容的测试使用）
        if not self.agent_mode:
            return self._scripted_response(prompt)

        # 工具已经执行过一轮：返回最终答复，结束 Agent 循环
        if _has_tool_message(messages):
            return AIMessage(content="已完成。")
        if self.SUMMARY_HINT in prompt:
            return AIMessage(content=self.FIXED_SUMMARY)

        # 主 Agent：发出 task 工具调用，真实走框架委派
        if self.MAIN_ROLE_HINT in prompt:
            if not self.delegate:
                return AIMessage(content="我直接处理，本轮不委派。")
            # 目标子 Agent 只从"当前这条指令"里判断：系统提示里列了全部子 Agent
            # 的职责说明，在整段提示里扫关键词会被系统提示带偏。
            instruction = _last_human_text(messages)
            target = next(
                (
                    name
                    for keyword, name in self.SUBAGENT_KEYWORDS.items()
                    if keyword in instruction
                ),
                None,
            )
            if target is not None:
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "task",
                            "args": {"subagent_type": target, "description": prompt[-160:]},
                            "id": f"call_task_{target}",
                            "type": "tool_call",
                        }
                    ],
                )
            return AIMessage(content="本轮无需委派。")

        # 子 Agent：调用自己的确定性能力工具
        for role, tool_name in self.ROLE_TOOL.items():
            if role in prompt:
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": tool_name,
                            "args": {},
                            "id": f"call_{tool_name}",
                            "type": "tool_call",
                        }
                    ],
                )

        return self._scripted_response(prompt)

    def _scripted_response(self, prompt: str) -> AIMessage:
        if self.script is not None:
            if not self.script:
                raise AssertionError("离线模型脚本已耗尽")
            return AIMessage(content=self.script.pop(0))
        if self.default_response is not None:
            return AIMessage(content=self.default_response)
        return AIMessage(
            content=json.dumps(
                parse_request_text(_extract_request(prompt)), ensure_ascii=False
            )
        )

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.calls.append(messages)
        return ChatResult(generations=[ChatGeneration(message=self._reply(messages))])


# 兼容旧名字
OfflineModel = OfflineChatModel


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
    if not isinstance(messages, (list, tuple)):
        return str(getattr(messages, "content", messages))
    parts: list[str] = []
    for message in messages or []:
        if isinstance(message, dict):
            parts.append(str(message.get("content", "")))
        else:
            parts.append(str(getattr(message, "content", message)))
    return "\n".join(parts)


def _has_tool_message(messages: Any) -> bool:
    if not isinstance(messages, (list, tuple)):
        return False
    return any(type(message).__name__ == "ToolMessage" for message in messages)


def _last_human_text(messages: Any) -> str:
    """取最后一条人类消息的内容。"""
    if not isinstance(messages, (list, tuple)):
        return str(getattr(messages, "content", messages))
    for message in reversed(messages):
        if type(message).__name__ == "HumanMessage":
            return str(getattr(message, "content", message))
    return _flatten(messages)


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

    def factory(**overrides: Any) -> OfflineChatModel:
        return OfflineChatModel(default_response=default_response, agent_mode=True)

    return factory
