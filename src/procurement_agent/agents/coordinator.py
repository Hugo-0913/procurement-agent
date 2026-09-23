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
    sourcing_items_to_payload,
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


def normalize_items(deps: CoordinatorDeps, parsed: dict[str, Any]) -> tuple[list[dict], str | None]:
    """把解析结果整理成物料清单。

    支持两种形态：模型返回 `items` 列表（多物料），或只返回单组字段（兼容旧行为）。
    返回 (items, 问题)；问题不为 None 时表示需要向用户澄清。
    """
    raw_items = parsed.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raw_items = [
            {
                "material_name": parsed.get("material_name"),
                "quantity": parsed.get("quantity"),
                "unit": parsed.get("unit"),
            }
        ]

    items: list[dict[str, Any]] = []
    for entry in raw_items:
        name = entry.get("material_name")
        quantity = entry.get("quantity")
        material = None
        if entry.get("material_id"):
            material = deps.repo.get_material(int(entry["material_id"]))
        elif name:
            material = deps.repo.find_material_by_name(str(name))
        if material is None and (name or entry.get("material_id")):
            return [], f"物料主数据中找不到「{name or entry.get('material_id')}」，请确认物料名称。"
        if not name and material is None:
            return [], "需求里缺少物料名称或数量，请补充后我再继续比价与下单。"
        if not quantity:
            return [], "需求里缺少物料名称或数量，请补充后我再继续比价与下单。"
        items.append(
            {
                "material_id": material.id,
                "material_name": material.name,
                "quantity": int(quantity),
                "unit": entry.get("unit") or material.unit,
            }
        )
    return items, None

# 注意：提示词里含 JSON 示例，必须用 replace 渲染而**不能用 str.format**，
# 否则示例中的花括号会被当成格式化占位符（曾因此抛 KeyError: '"items"'）。
PARSE_PROMPT = """你是采购需求解析器。请把下面的采购需求解析为 JSON。
只输出 JSON，不要输出任何解释文字。

单种物料时输出：material_name（必填）、quantity（必填，整数）、unit、expected_date、
budget、cost_center、note。缺失的可选字段填 null，禁止猜测未提及的信息。

需求包含多种物料时，改为输出 items 数组，每种物料一个元素：
{"items":[{"material_name":"...","quantity":10,"unit":"..."}, ...],
 "expected_date":null,"budget":null,"cost_center":"...","note":null}
不要在 items 之外重复输出 material_name 与 quantity。

{skill_index}

采购需求：{request_text}
"""


def build_parse_prompt(skill_index: str, request_text: str) -> str:
    return PARSE_PROMPT.replace("{skill_index}", skill_index).replace(
        "{request_text}", request_text
    )


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
    """加载技能并记录事件。调用方需自行保证同一任务内不重复。"""
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
            loaded_skills=set(context.get("loaded_skills", [])),
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

        record = deps.store.get_task(task_id)
        prefilled = context.get("prefilled") or {}
        loaded = set(context.get("loaded_skills", []))

        if prefilled.get("items"):
            # 点选式下单：物料与数量由用户直接选择，跳过模型解析，
            # 因此这里不加载需求解析技能（页面上的技能状态会如实反映这一点）。
            parsed = {
                "items": prefilled["items"],
                "cost_center": prefilled.get("cost_center"),
                "expected_date": prefilled.get("expected_date"),
                "budget": None,
                "note": None,
                "source": "form",
            }
            _event(
                deps,
                task_id,
                "coordinator",
                "tool_result",
                {"tool": "requirement_parser", "summary": "用户直接选择了物料，跳过解析"},
            )
        else:
            if "requirement_parsing" not in loaded:
                _load_skill(deps, task_id, "coordinator", "requirement_parsing")
                loaded.add("requirement_parsing")

            model = deps.model_factory()
            prompt = build_parse_prompt(deps.skills.render_index(), record.request_text)
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

        if not is_iso_date(parsed.get("expected_date")):
            parsed["expected_date"] = parse_relative_date(parsed.get("expected_date")) or parsed.get(
                "expected_date"
            )
        _event(
            deps,
            task_id,
            "coordinator",
            "tool_result",
            {"tool": "requirement_parser", "summary": "已解析采购要素"},
        )

        items, problem = normalize_items(deps, parsed)
        if problem is not None:
            missing = [
                field
                for field in REQUIRED_PARSE_FIELDS
                if not parsed.get(field) and "找不到" not in problem
            ]
            _event(
                deps,
                task_id,
                "coordinator",
                "clarification_requested",
                {"question": problem, "missing": missing},
            )
            return StageResult(
                state=TaskState.AWAITING_CLARIFICATION,
                payload={
                    "needs_clarification": True,
                    "question": problem,
                    "missing_fields": missing,
                    "structured_request": parsed,
                },
            )

        first = items[0]
        # 同时保存归一化后的物料清单，供页面展示与后续追溯
        deps.store.set_structured_request(task_id, {**parsed, "items": items})
        return StageResult(
            state=TaskState.PARSING,
            payload={
                "needs_clarification": False,
                "structured_request": parsed,
                "items": items,
                "item_count": len(items),
                "material_id": first["material_id"],
                "material_name": first["material_name"],
                "quantity": first["quantity"],
                "cost_center": parsed.get("cost_center") or "CC-1001",
                "expected_date": parsed.get("expected_date"),
                "loaded_skills": sorted(loaded),
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
        qualification_payload = task_context.results["qualification_payload"]
        result = StageResult(
            state=TaskState.QUALIFYING,
            payload={
                "qualification": qualification_payload,
                "loaded_skills": sorted(task_context.loaded_skills),
            },
        )
        result.payload.update(
            _track_context(
                deps,
                task_id,
                context,
                {
                    "step": "qualification",
                    "materials": len(qualification_payload["by_material"]),
                },
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
        sourcing_items = task_context.results["sourcing_items"]
        result = StageResult(
            state=TaskState.SOURCING,
            payload={
                "sourcing": sourcing_items_to_payload(sourcing_items),
                "loaded_skills": sorted(task_context.loaded_skills),
            },
        )
        result.payload.update(
            _track_context(
                deps,
                task_id,
                context,
                {
                    "step": "sourcing",
                    "items": len(sourcing_items),
                    "comparisons": sum(
                        len(item["outcome"].comparisons) for item in sourcing_items
                    ),
                },
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
        drafts = task_context.results["drafts"]
        decision = task_context.results["decision"]
        result = StageResult(
            state=TaskState.ORDER_DRAFTING,
            payload={
                "drafts": [draft_to_payload(draft) for draft in drafts],
                "draft": draft_to_payload(drafts[0]),
                "needs_approval": decision.requires_approval,
                "matched_rules": list(decision.matched_rules),
                "loaded_skills": sorted(task_context.loaded_skills),
            },
        )
        result.payload.update(
            _track_context(
                deps,
                task_id,
                context,
                {
                    "step": "order_draft",
                    "lines": len(drafts),
                    "total": round(sum(item.total_amount for item in drafts), 2),
                },
                {"quantity": context.get("quantity"), "material": context.get("material_name")},
            )
        )
        return result

    def ordering(task_id: str, context: dict[str, Any]) -> StageResult:
        target = agents.subagents["ordering"].name
        drafts = [payload_to_draft(item) for item in context["drafts"]]
        if (
            context.get("sourcing", {}).get("insufficient_quotes")
            and deps.config.single_quote_policy == "fail"
        ):
            raise InsufficientQuotesError()
        order_ids: list[int] = []
        for draft in drafts:
            order_ids.append(deps.repo.create_order(draft))
            deps.repo.record_price(draft.supplier_id, draft.material_id, draft.unit_price)
        _event(
            deps,
            task_id,
            target,
            "tool_result",
            {"tool": "order_create", "order_id": order_ids[0], "order_ids": order_ids},
        )
        if deps.memory is not None:
            for draft in drafts:
                supplier = deps.repo.supplier(draft.supplier_id)
                deps.memory.record_order_outcome(
                    supplier_code=supplier.code if supplier else str(draft.supplier_id),
                    sku=str(context.get("material_name", "")),
                    unit_price=draft.unit_price,
                    approved=True,
                )
            _event(deps, task_id, "coordinator", "memory_written", {"sku": context.get("material_name")})
        return StageResult(
            state=TaskState.ORDERED,
            payload={"order_id": order_ids[0], "order_ids": order_ids},
        )

    return {
        TaskState.PARSING: parsing,
        TaskState.QUALIFYING: qualifying,
        TaskState.SOURCING: sourcing,
        TaskState.ORDER_DRAFTING: order_drafting,
        TaskState.ORDERED: ordering,
    }
