"""主 Agent 通过 DeepAgents 框架的 task 工具真实委派子 Agent。

设计要点：

1. **委派是真实的。** 主 Agent 运行在 ``create_deep_agent`` 构造的图上，靠模型自己决定
   调用 ``task`` 工具把任务交给子 Agent；``agent_delegation`` 事件从真实的消息轨迹里
   提取，而不是由状态机"记账"。
2. **业务判定仍然是确定性的。** 子 Agent 的能力以零参数工具形式提供，工具从当前任务
   上下文读取参数、调用确定性函数、把结构化结果写回上下文。模型负责"决定调用哪个工具"，
   不负责计算金额与判断资质。
3. **失败可降级且可见。** 如果模型没有调用 ``task`` 工具（或调用出错），自动降级为直接
   调用确定性函数，并写出 ``delegation_result`` 事件把 mode 标成 fallback，绝不假装成功。
"""

from __future__ import annotations

import json
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Callable

from procurement_agent.agents.ordering import build_order_draft
from procurement_agent.agents.payloads import (
    draft_to_payload,
    qualification_from_payload,
    qualification_to_payload,
    sourcing_from_payload,
    sourcing_items_from_payload,
    sourcing_items_to_payload,
    sourcing_to_payload,
)
from procurement_agent.agents.qualification import run_qualification
from procurement_agent.agents.sourcing import run_sourcing
from procurement_agent.middleware.token_usage import TokenUsageCallback
from procurement_agent.skills_loader import SkillRegistry
from procurement_agent.state.store import TaskStore

QUALIFICATION_AGENT = "qualification_agent"
SOURCING_AGENT = "sourcing_agent"
ORDERING_AGENT = "ordering_agent"

MAIN_SYSTEM_PROMPT = """你是企业医用耗材采购的主 Agent（采购协调者）。

你必须通过 task 工具把工作委派给对应的子 Agent，自己不要代替子 Agent 完成核验、比价或下单：
- qualification_agent：核验供应商资质
- sourcing_agent：在合格供应商之间比价
- ordering_agent：生成订单草稿并判断是否需要审批

收到用户指令后，直接调用 task 工具把任务交给最合适的子 Agent，description 里写清要做什么。
子 Agent 返回结果后，用一句话总结即可，不要重复它给出的明细。"""

SUBAGENT_SPECS: tuple[dict[str, Any], ...] = (
    {
        "name": QUALIFICATION_AGENT,
        "description": "核验候选供应商的资质、有效期与黑名单状态时使用。",
        "system_prompt": (
            "你是资质核验专员。你必须调用 qualification_query 工具获取核验结果，"
            "然后转述合格与淘汰的数量。不要自行编造供应商数据。"
        ),
        "tool_name": "qualification_query",
    },
    {
        "name": SOURCING_AGENT,
        "description": "在合格供应商之间比较报价、计算综合成本并给出推荐时使用。",
        "system_prompt": (
            "你是比价分析专员。你必须调用 quote_query 工具获取比价结果，"
            "然后转述推荐结论与理由。不要自行编造价格。"
        ),
        "tool_name": "quote_query",
    },
    {
        "name": ORDERING_AGENT,
        "description": "生成订单草稿并判断是否触发人工审批时使用。",
        "system_prompt": (
            "你是订单执行专员。你必须调用 order_draft 工具生成订单草稿并判定是否需要审批，"
            "然后转述草稿金额与是否转人工。不要自行决定下单。"
        ),
        "tool_name": "order_draft",
    },
)


@dataclass
class TaskContext:
    """一次任务在委派期间的共享上下文。"""

    task_id: str
    store: TaskStore
    repo: Any
    config: Any
    policy: Any
    skills: SkillRegistry
    state: dict[str, Any] = field(default_factory=dict)
    results: dict[str, Any] = field(default_factory=dict)
    loaded_skills: set[str] = field(default_factory=set)


CURRENT_TASK: ContextVar[TaskContext | None] = ContextVar(
    "procurement_current_task", default=None
)


def _ctx() -> TaskContext:
    context = CURRENT_TASK.get()
    if context is None:
        raise RuntimeError("当前没有活动的任务上下文，无法执行子 Agent 工具")
    return context


def _load_skill(context: TaskContext, agent: str, name: str) -> None:
    """按任务维度记录技能加载。

    不能用注册表的进程级 ``loaded_names`` 判断：并发跑多个任务时，第二个任务会因为
    技能"已在进程内加载过"而漏发 skill_loaded 事件，页面就会把它显示成"仅描述"。
    """
    if name in context.loaded_skills:
        return
    context.skills.load(name)
    context.loaded_skills.add(name)
    context.store.append_event(
        context.task_id, agent, "skill_loaded", {"skill": name}
    )


def _emit(context: TaskContext, agent: str, kind: str, payload: dict[str, Any]) -> None:
    context.store.append_event(context.task_id, agent, kind, payload)


def qualification_query() -> str:
    """核验候选供应商资质，返回合格与淘汰清单的 JSON。"""
    context = _ctx()
    _emit(context, QUALIFICATION_AGENT, "tool_call", {"tool": "supplier_qualification_query"})
    _load_skill(context, QUALIFICATION_AGENT, "supplier_qualification")
    outcome = run_qualification(
        context.repo, context.config, int(context.state["material_id"])
    )
    context.results["qualification"] = outcome
    payload = qualification_to_payload(outcome)
    _emit(
        context,
        QUALIFICATION_AGENT,
        "tool_result",
        {
            "tool": "supplier_qualification_query",
            "summary": f"合格 {len(outcome.qualified)} 家，淘汰 {len(outcome.rejected)} 家",
        },
    )
    return json.dumps(payload, ensure_ascii=False)


def quote_query() -> str:
    """对需求中的每种物料分别比价，返回多物料比价结果的 JSON。"""
    context = _ctx()
    _emit(context, SOURCING_AGENT, "tool_call", {"tool": "quote_query"})
    _load_skill(context, SOURCING_AGENT, "price_comparison")

    qualified = context.results.get("qualification")
    if qualified is None:
        qualified = qualification_from_payload(context.state["qualification"])

    items = _items_of(context)
    results = [
        {
            **item,
            "outcome": run_sourcing(
                context.repo,
                context.config,
                int(item["material_id"]),
                int(item["quantity"]),
                qualified,
                expected_date=context.state.get("expected_date"),
            ),
        }
        for item in items
    ]
    context.results["sourcing_items"] = results
    payload = sourcing_items_to_payload(results)
    _emit(
        context,
        SOURCING_AGENT,
        "tool_result",
        {
            "tool": "quote_query",
            "summary": payload["reason"],
            "comparisons": sum(len(item["outcome"].comparisons) for item in results),
            "detail": payload,
        },
    )
    return json.dumps(payload, ensure_ascii=False)


def order_draft() -> str:
    """为每种物料生成一行订单草稿，按合计金额判定是否需要人工审批。"""
    context = _ctx()
    _emit(context, ORDERING_AGENT, "tool_call", {"tool": "order_draft"})
    _load_skill(context, ORDERING_AGENT, "order_compliance")

    items = _items_of(context)
    outcomes = sourcing_items_from_payload(context.state["sourcing"])
    cost_center = str(context.state.get("cost_center") or "CC-1001")
    drafts = [
        build_order_draft(outcome, int(item["material_id"]),
                          int(item["quantity"]), cost_center, context.task_id)
        for item, outcome in zip(items, outcomes)
    ]
    decision = context.policy.check_lines(drafts)
    context.results["drafts"] = drafts
    context.results["decision"] = decision
    payload = {
        "drafts": [draft_to_payload(draft) for draft in drafts],
        "requires_approval": decision.requires_approval,
        "matched_rules": list(decision.matched_rules),
        "total_amount": round(sum(draft.total_amount for draft in drafts), 2),
    }
    _emit(
        context,
        ORDERING_AGENT,
        "tool_result",
        {
            "tool": "order_draft",
            "summary": f"订单草稿 {len(drafts)} 行，合计 ¥{payload['total_amount']:.2f}",
            "requires_approval": decision.requires_approval,
            "draft": payload["drafts"][0],
            "drafts": payload["drafts"],
            "matched_rules": payload["matched_rules"],
            "recommendation_reason": "；".join(
                outcome.reason for outcome in outcomes if outcome.reason
            ),
        },
    )
    return json.dumps(payload, ensure_ascii=False)


def _items_of(context: TaskContext) -> list[dict[str, Any]]:
    """取需求中的物料清单；兼容只有单物料的旧任务。"""
    items = context.state.get("items")
    if items:
        return list(items)
    return [
        {
            "material_id": context.state["material_id"],
            "material_name": context.state.get("material_name"),
            "quantity": context.state["quantity"],
        }
    ]


TOOL_BY_NAME: dict[str, Callable[[], str]] = {
    "qualification_query": qualification_query,
    "quote_query": quote_query,
    "order_draft": order_draft,
}


def extract_task_calls(messages: Any) -> list[dict[str, Any]]:
    """从消息轨迹中提取真实的 task 工具调用。"""
    calls: list[dict[str, Any]] = []
    for message in messages or []:
        for call in getattr(message, "tool_calls", None) or []:
            if isinstance(call, dict) and call.get("name") == "task":
                calls.append(call.get("args") or {})
    return calls


class DelegationRuntime:
    """构造一次主 Agent 图，并负责设置任务上下文。"""

    def __init__(self, model_factory: Callable[..., Any], agents_config: Any = None) -> None:
        self._model_factory = model_factory
        self._agents_config = agents_config
        self._agent = None

    @property
    def agent(self):
        if self._agent is None:
            self._agent = self._build()
        return self._agent

    def _build(self):
        from deepagents import create_deep_agent

        subagents = [
            {
                "name": spec["name"],
                "description": spec["description"],
                "system_prompt": spec["system_prompt"],
                "tools": [TOOL_BY_NAME[spec["tool_name"]]],
            }
            for spec in SUBAGENT_SPECS
        ]
        return create_deep_agent(
            model=self._model_factory(),
            tools=[],
            system_prompt=MAIN_SYSTEM_PROMPT,
            subagents=subagents,
        )

    def delegate(self, context: TaskContext, subagent: str, instruction: str) -> str:
        """请求主 Agent 委派指定子 Agent，并返回主 Agent 的最终回复。"""
        token = CURRENT_TASK.set(context)
        try:
            result = self.agent.invoke(
                {"messages": [{"role": "user", "content": instruction}]},
                {"callbacks": [TokenUsageCallback(context.store, context.task_id)]},
            )
        finally:
            CURRENT_TASK.reset(token)

        messages = result.get("messages", []) if isinstance(result, dict) else []
        calls = extract_task_calls(messages)
        for call in calls:
            if call.get("subagent_type") == subagent:
                _emit(
                    context,
                    "coordinator",
                    "delegation_result",
                    {"to": subagent, "mode": "framework"},
                )
                return "framework"
        _emit(
            context,
            "coordinator",
            "delegation_result",
            {
                "to": subagent,
                "mode": "fallback",
                "reason": "模型未调用 task 工具，已降级为直接执行",
                "call_count": len(calls),
            },
        )
        return "fallback"

    def run_tool_directly(self, context: TaskContext, tool_name: str) -> None:
        """降级路径：直接执行子 Agent 的能力工具。"""
        token = CURRENT_TASK.set(context)
        try:
            TOOL_BY_NAME[tool_name]()
        finally:
            CURRENT_TASK.reset(token)
