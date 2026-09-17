from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from procurement_agent.agents.config import AgentsConfig
from procurement_agent.agents.delegation import (
    ORDERING_AGENT,
    QUALIFICATION_AGENT,
    SOURCING_AGENT,
    DelegationRuntime,
    TaskContext,
)
from procurement_agent.agents.dates import is_iso_date, parse_relative_date
from procurement_agent.agents.model import build_chat_model
from procurement_agent.agents.ordering import InsufficientQuotesError
from procurement_agent.agents.payloads import (
    draft_to_payload,
    payload_to_draft,
    qualification_from_payload,
    qualification_to_payload,
    sourcing_from_payload,
    sourcing_to_payload,
)
from procurement_agent.agents.response import response_text
from procurement_agent.config import ProcurementConfig
from procurement_agent.erp.repository import ErpRepository
from procurement_agent.middleware.reflection_retry import RetryExhausted, run_with_retry
from procurement_agent.middleware.token_usage import TokenUsageCallback
from procurement_agent.sandbox.policy import PolicyEngine
from procurement_agent.skills_loader import SkillRegistry
from procurement_agent.state.models import TaskState
from procurement_agent.state.nodes import StageResult
from procurement_agent.state.store import TaskStore

REQUIRED_PARSE_FIELDS = ("material_name", "quantity")

PARSE_PROMPT = """你是采购需求解析器。请把下面的采购需求解析为 JSON。
只输出 JSON，不要输出任何解释文字。

字段要求：material_name（必填）、quantity（必填，整数）、unit、expected_date、
budget、cost_center、note。缺失的可选字段填 null，禁止猜测未提及的信息。

{skill_index}

采购需求：{request_text}
"""


@dataclass
class CoordinatorDeps:
    repo: ErpRepository
    store: TaskStore
    config: ProcurementConfig
    agents_config: AgentsConfig
    skills: SkillRegistry
    policy: PolicyEngine
    model_factory: Callable[..., Any] = build_chat_model
    memory: Any | None = None
    summarizer: Any | None = None
    retry: Any | None = None


def _event(deps: CoordinatorDeps, task_id: str, agent: str, kind: str, payload: dict) -> None:
    deps.store.append_event(task_id, agent, kind, payload)


def _load_skill(deps: CoordinatorDeps, task_id: str, agent: str, name: str) -> None:
    if name in deps.skills.loaded_names:
        return
    deps.skills.load(name)
    _event(deps, task_id, agent, "skill_loaded", {"skill": name})


def _delegate(deps: CoordinatorDeps, task_id: str, target: str) -> None:
    _event(
        deps,
        task_id,
        "coordinator",
        "agent_delegation",
        {"from": "coordinator", "to": target},
    )


def _call_subagent(deps: CoordinatorDeps, task_id: str, agent: str, fn: Callable[[], Any]) -> Any:
    """子 Agent 调用统一经过反思重试中间件。"""
    return run_with_retry(
        lambda _attempt: fn(),
        max_attempts=deps.config.retry_max_attempts,
        store=deps.store,
        task_id=task_id,
        agent=agent,
    )


def _track_context(
    deps: CoordinatorDeps,
    task_id: str,
    context: dict[str, Any],
    entry: dict[str, Any],
    essential: dict[str, Any],
) -> dict[str, Any]:
    """累积工具返回记录，必要时触发上下文摘要并产生可观测事件。"""
    transcript = list(context.get("transcript", []))
    transcript.append({"role": "tool", "content": json.dumps(entry, ensure_ascii=False)})
    update: dict[str, Any] = {"transcript": transcript}
    if deps.summarizer is not None:
        messages, summary = deps.summarizer.maybe_summarize(transcript, essential)
        if summary is not None:
            _event(
                deps,
                task_id,
                "context_summarizer",
                "context_summarized",
                {
                    "before_tokens": summary.before_tokens,
                    "after_tokens": summary.after_tokens,
                    "dropped_categories": list(summary.dropped_categories),
                },
            )
            deps.store.add_tokens(task_id, 0, total=summary.after_tokens)
            update["transcript"] = messages
            update["last_summary"] = {
                "before_tokens": summary.before_tokens,
                "after_tokens": summary.after_tokens,
            }
        else:
            deps.store.add_tokens(
                task_id, 0, total=deps.summarizer.estimate_messages(transcript, essential)
            )
    return update


def build_handlers(deps: CoordinatorDeps):
    agents = deps.agents_config
    runtime = DelegationRuntime(deps.model_factory, agents)

    def run_delegated(
        task_id: str,
        context: dict[str, Any],
        subagent: str,
        tool_name: str,
        instruction: str,
        result_key: str,
    ) -> TaskContext:
        """委派子 Agent 执行一个阶段；模型未调用 task 工具时降级为直接执行。"""
        task_context = TaskContext(
            task_id=task_id,
            store=deps.store,
            repo=deps.repo,
            config=deps.config,
            policy=deps.policy,
            skills=deps.skills,
            state=dict(context),
        )
        _delegate(deps, task_id, subagent)
        mode = "fallback"
        try:
            mode = _call_subagent(
                deps,
                task_id,
                subagent,
                lambda: runtime.delegate(task_context, subagent, instruction),
            )
        except RetryExhausted as exc:
            task_context.store.append_event(
                task_id,
                "coordinator",
                "delegation_result",
                {
                    "to": subagent,
                    "mode": "fallback",
                    "reason": f"委派失败：{type(exc.last_error).__name__}",
                },
            )
        if mode == "fallback" or result_key not in task_context.results:
            runtime.run_tool_directly(task_context, tool_name)
        return task_context

    def parsing(task_id: str, context: dict[str, Any]) -> StageResult:
        if deps.memory is not None:
            block = deps.memory.render_prompt_block()
            _event(deps, task_id, "coordinator", "memory_loaded", {"summary": block})
        _load_skill(deps, task_id, "coordinator", "requirement_parsing")

        record = deps.store.get_task(task_id)
        model = deps.model_factory()
        prompt = PARSE_PROMPT.format(
            skill_index=deps.skills.render_index(),
            request_text=record.request_text,
        )
        _event(deps, task_id, "coordinator", "tool_call", {"tool": "requirement_parser"})

        def parse_once() -> dict[str, Any]:
            """模型调用与结构化校验放在同一个可重试单元内：
            模型返回非法 JSON 时按可重试错误处理，而不是直接判失败。"""
            raw = model.invoke([{"role": "user", "content": prompt}])
            TokenUsageCallback(deps.store, task_id).record_message(raw)
            return json.loads(response_text(raw))

        parsed = _call_subagent(deps, task_id, "coordinator", parse_once)
        # 模型常把"下周一"原样返回，这里用确定性规则换算为 ISO 日期
        if not is_iso_date(parsed.get("expected_date")):
            parsed["expected_date"] = parse_relative_date(
                parsed.get("expected_date")
            ) or parse_relative_date(record.request_text)
        _event(
            deps,
            task_id,
            "coordinator",
            "tool_result",
            {"tool": "requirement_parser", "summary": "已解析采购要素"},
        )

        missing = [field for field in REQUIRED_PARSE_FIELDS if not parsed.get(field)]
        if missing:
            question = "请补充采购物料名称与数量，我才能继续。"
            return StageResult(
                state=TaskState.PARSING,
                payload={
                    "needs_clarification": True,
                    "question": question,
                    "structured_request": parsed,
                },
            )

        material = deps.repo.find_material_by_name(str(parsed["material_name"]))
        if material is None:
            return StageResult(
                state=TaskState.PARSING,
                payload={
                    "needs_clarification": True,
                    "question": f"物料主数据中找不到「{parsed['material_name']}」，请确认物料名称。",
                    "structured_request": parsed,
                },
            )

        deps.store.set_structured_request(task_id, parsed)
        return StageResult(
            state=TaskState.PARSING,
            payload={
                "needs_clarification": False,
                "structured_request": parsed,
                "material_id": material.id,
                "material_name": material.name,
                "quantity": int(parsed["quantity"]),
                "cost_center": parsed.get("cost_center") or "CC-1001",
            },
        )

    def qualifying(task_id: str, context: dict[str, Any]) -> StageResult:
        task_context = run_delegated(
            task_id,
            context,
            agents.subagents["qualification"].name,
            "qualification_query",
            "请委派资质核验子 Agent 核验本次采购候选供应商的资质与有效期。",
            "qualification",
        )
        outcome = task_context.results["qualification"]
        result = StageResult(
            state=TaskState.QUALIFYING,
            payload={"qualification": qualification_to_payload(outcome)},
        )
        result.payload.update(
            _track_context(
                deps,
                task_id,
                context,
                {"step": "qualification", "qualified": len(outcome.qualified)},
                {"quantity": context.get("quantity"), "material": context.get("material_name")},
            )
        )
        return result

    def sourcing(task_id: str, context: dict[str, Any]) -> StageResult:
        task_context = run_delegated(
            task_id,
            context,
            agents.subagents["sourcing"].name,
            "quote_query",
            "请委派比价分析子 Agent 在合格供应商之间比价并给出推荐与理由。",
            "sourcing",
        )
        outcome = task_context.results["sourcing"]
        result = StageResult(
            state=TaskState.SOURCING, payload={"sourcing": sourcing_to_payload(outcome)}
        )
        result.payload.update(
            _track_context(
                deps,
                task_id,
                context,
                {"step": "sourcing", "comparisons": len(outcome.comparisons)},
                {"quantity": context.get("quantity"), "material": context.get("material_name")},
            )
        )
        return result

    def order_drafting(task_id: str, context: dict[str, Any]) -> StageResult:
        task_context = run_delegated(
            task_id,
            context,
            agents.subagents["ordering"].name,
            "order_draft",
            "请委派订单执行子 Agent 生成订单草稿并判断是否需要人工审批。",
            "draft",
        )
        draft = task_context.results["draft"]
        decision = task_context.results["decision"]
        result = StageResult(
            state=TaskState.ORDER_DRAFTING,
            payload={
                "draft": draft_to_payload(draft),
                "needs_approval": decision.requires_approval,
                "matched_rules": list(decision.matched_rules),
            },
        )
        result.payload.update(
            _track_context(
                deps,
                task_id,
                context,
                {"step": "order_draft", "total": draft.total_amount},
                {"quantity": context.get("quantity"), "material": context.get("material_name")},
            )
        )
        return result

    def ordering(task_id: str, context: dict[str, Any]) -> StageResult:
        target = agents.subagents["ordering"].name
        draft = payload_to_draft(context["draft"])
        if context.get("sourcing", {}).get("insufficient_quotes"):
            raise InsufficientQuotesError()
        order_id = deps.repo.create_order(draft)
        deps.repo.record_price(draft.supplier_id, draft.material_id, draft.unit_price)
        _event(
            deps,
            task_id,
            target,
            "tool_result",
            {"tool": "order_create", "order_id": order_id},
        )
        if deps.memory is not None:
            supplier = deps.repo.supplier(draft.supplier_id)
            deps.memory.record_order_outcome(
                supplier_code=supplier.code if supplier else str(draft.supplier_id),
                sku=str(context.get("material_name", "")),
                unit_price=draft.unit_price,
                approved=True,
            )
            _event(deps, task_id, "coordinator", "memory_written", {"sku": context.get("material_name")})
        return StageResult(state=TaskState.ORDERED, payload={"order_id": order_id})

    return {
        TaskState.PARSING: parsing,
        TaskState.QUALIFYING: qualifying,
        TaskState.SOURCING: sourcing,
        TaskState.ORDER_DRAFTING: order_drafting,
        TaskState.ORDERED: ordering,
    }
