from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator, model_validator

from procurement_agent.config import ProcurementConfig
from procurement_agent.erp.faults import ALL_FLAGS, FLAG_LABELS, FaultRegistry
from procurement_agent.erp.repository import ErpRepository
from procurement_agent.memory.store import MemoryStore
from procurement_agent.skills_loader import SkillRegistry
from procurement_agent.state.graph import TaskRunner
from procurement_agent.state.models import STAGE_LABELS, TaskState
from procurement_agent.state.store import TaskStore
from procurement_agent.web.events import event_stream


@dataclass
class WebContext:
    config: ProcurementConfig
    repo: ErpRepository
    store: TaskStore
    runner: TaskRunner
    faults: FaultRegistry
    skills: SkillRegistry
    memory: MemoryStore
    templates: Any
    eval_runner: Any | None = None
    offline: bool = False


class CreateTaskRequest(BaseModel):
    """两种下单方式：点选式（items）或自然语言（request_text）。"""

    request_text: str | None = None
    items: list[dict[str, Any]] | None = None
    cost_center: str | None = None
    expected_date: str | None = None

    @model_validator(mode="after")
    def check_input(self) -> "CreateTaskRequest":
        has_items = bool(self.items)
        has_text = bool(self.request_text and self.request_text.strip())
        if not has_items and not has_text:
            raise ValueError("请选择要采购的物料，或填写采购需求")
        if self.request_text:
            self.request_text = self.request_text.strip()
        if has_items:
            for item in self.items or []:
                if not item.get("material_id"):
                    raise ValueError("每一行都要选择物料")
                try:
                    quantity = int(item.get("quantity") or 0)
                except (TypeError, ValueError) as exc:
                    raise ValueError("数量必须是整数") from exc
                if quantity <= 0:
                    raise ValueError("数量必须大于 0")
                item["quantity"] = quantity
        return self


class ApprovalRequest(BaseModel):
    decision: str
    operator: str = "采购主管"
    reason: str = ""

    @field_validator("decision")
    @classmethod
    def known_decision(cls, value: str) -> str:
        if value not in {"approve", "reject", "revise"}:
            raise ValueError("decision 必须是 approve / reject / revise")
        return value

    @field_validator("reason")
    @classmethod
    def reason_required_for_reject(cls, value: str, info) -> str:
        decision = info.data.get("decision")
        if decision in {"reject", "revise"} and not value.strip():
            raise ValueError("驳回或要求修改时必须填写理由")
        return value.strip()


class FaultRequest(BaseModel):
    flag: str
    enabled: bool


class ClarificationRequest(BaseModel):
    answer: str

    @field_validator("answer")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("补充说明不能为空")
        return value.strip()


def _event_payload(store: TaskStore, task_id: str, event_type: str) -> dict[str, Any] | None:
    events = [e for e in store.list_events(task_id) if e.event_type == event_type]
    return events[-1].payload if events else None


def _from_selection(
    ctx: WebContext, payload: CreateTaskRequest
) -> tuple[dict[str, Any], str]:
    """把点选式下单转成流程可用的结构化输入，并拼一句人能读懂的需求描述。

    用户点选的是物料 ID 与数量，这里查主数据补全名称与单位，既用于展示，也用于日志追溯。
    """
    items: list[dict[str, Any]] = []
    parts: list[str] = []
    for row in payload.items or []:
        material = ctx.repo.get_material(int(row["material_id"]))
        if material is None:
            raise HTTPException(status_code=422, detail="所选物料不在采购目录中")
        quantity = int(row["quantity"])
        unit = row.get("unit") or material.unit
        items.append({"material_id": material.id, "quantity": quantity})
        parts.append(f"{quantity} {unit}{material.name}")

    text = "采购 " + "、".join(parts)
    if payload.cost_center:
        text += f"，成本中心 {payload.cost_center}"
    return (
        {
            "items": items,
            "cost_center": payload.cost_center,
            "expected_date": payload.expected_date,
        },
        text,
    )


def build_task_detail(ctx: WebContext, task_id: str) -> dict[str, Any]:
    try:
        record = ctx.store.get_task(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc

    events = ctx.store.list_events(task_id)
    loaded_skills = [
        event.payload["skill"] for event in events if event.event_type == "skill_loaded"
    ]
    all_skills = [meta.name for meta in ctx.skills.list_metadata()]

    pending = None
    pending_clarification = None
    if record.state is TaskState.AWAITING_CLARIFICATION:
        requested = _event_payload(ctx.store, task_id, "clarification_requested") or {}
        pending_clarification = {
            "question": requested.get("question", "请补充缺失的采购信息。"),
            "missing": requested.get("missing", []),
        }
    if record.state is TaskState.AWAITING_APPROVAL:
        requested = _event_payload(ctx.store, task_id, "approval_requested") or {}
        draft_event = next(
            (
                event.payload
                for event in reversed(events)
                if event.event_type == "tool_result"
                and event.payload.get("tool") == "order_draft"
            ),
            {},
        )
        order_lines = draft_event.get("drafts") or (
            [draft_event["draft"]] if draft_event.get("draft") else []
        )
        # 订单行只带 material_id：审批人必须能看出"这一行买的是什么"，
        # 否则多物料订单的审批卡片上是几行没有名字的报价，无法核单。
        material_names = {m.id: m.name for m in ctx.repo.list_materials()}
        order_lines = [
            {
                **line,
                "material_name": material_names.get(
                    line.get("material_id"), str(line.get("material_id"))
                ),
            }
            for line in order_lines
        ]
        pending = {
            "matched_rules": requested.get("matched_rules", []),
            "order_draft": order_lines[0] if order_lines else None,
            "order_lines": order_lines,
            "total_amount": round(
                sum(line.get("total_amount", 0) for line in order_lines), 2
            ),
            "recommendation_reason": draft_event.get("recommendation_reason", ""),
        }

    order_event = next(
        (
            event.payload
            for event in reversed(events)
            if event.event_type == "tool_result" and event.payload.get("tool") == "order_create"
        ),
        None,
    )
    sourcing_detail = None
    for event in reversed(events):
        if event.event_type == "tool_result" and event.payload.get("tool") == "quote_query":
            sourcing_detail = event.payload.get("detail")
            break

    return {
        "id": record.id,
        "request_text": record.request_text,
        "state": record.state.value,
        "state_label": STAGE_LABELS[record.state],
        "structured_request": record.structured_request,
        "request_items": (record.structured_request or {}).get("items", []),
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "finished_at": record.finished_at,
        "human_interventions": record.human_interventions,
        "token_usage": record.token_usage,
        "loaded_skills": sorted(set(loaded_skills)),
        "metadata_only_skills": [s for s in all_skills if s not in set(loaded_skills)],
        "memory_block": ctx.memory.render_prompt_block(),
        "pending_approval": pending,
        "pending_clarification": pending_clarification,
        "order_id": order_event.get("order_id") if order_event else None,
        "sourcing": sourcing_detail,
        "events": [
            {
                "seq": event.seq,
                "agent": event.agent,
                "event_type": event.event_type,
                "payload": event.payload,
                "created_at": event.created_at,
            }
            for event in events
        ],
    }


def build_router(ctx: WebContext) -> APIRouter:
    router = APIRouter()

    # ---------- 页面 ----------

    @router.get("/", include_in_schema=False)
    def board_page(request: Request):
        return ctx.templates.TemplateResponse(
            request, "board.html", {"nav": "board", "offline_mode": ctx.offline}
        )

    @router.get("/tasks/{task_id}", include_in_schema=False)
    def task_page(request: Request, task_id: str):
        return ctx.templates.TemplateResponse(
            request,
            "task.html",
            {"nav": "board", "task_id": task_id, "offline_mode": ctx.offline},
        )

    @router.get("/data", include_in_schema=False)
    def data_page(request: Request):
        flags = ctx.faults.list_flags()
        return ctx.templates.TemplateResponse(
            request,
            "data.html",
            {
                "nav": "data",
                "offline_mode": ctx.offline,
                "fault_flags": [
                    {"flag": flag, "label": FLAG_LABELS.get(flag, flag), "enabled": flags.get(flag, False)}
                    for flag in ALL_FLAGS
                ],
            },
        )

    @router.get("/eval", include_in_schema=False)
    def eval_page(request: Request):
        return ctx.templates.TemplateResponse(
            request, "eval.html", {"nav": "eval", "offline_mode": ctx.offline}
        )

    # ---------- 任务 ----------

    @router.post("/api/tasks")
    def create_task(payload: CreateTaskRequest) -> dict[str, str]:
        if payload.items:
            prefilled, request_text = _from_selection(ctx, payload)
        else:
            prefilled = {}
            request_text = payload.request_text or ""
        task_id = ctx.store.create_task(request_text)

        def run() -> None:
            ctx.runner.run(task_id, request_text, prefilled or None)

        threading.Thread(target=run, name=f"task-{task_id}", daemon=True).start()
        return {"task_id": task_id}

    @router.get("/api/tasks")
    def list_tasks(state: str | None = None) -> list[dict[str, Any]]:
        target = TaskState(state) if state else None
        return [
            {
                "id": record.id,
                "request_text": record.request_text,
                "state": record.state.value,
                "state_label": STAGE_LABELS[record.state],
                "summary": record.request_text[:40],
                "created_at": record.created_at,
                "updated_at": record.updated_at,
                "human_interventions": record.human_interventions,
            }
            for record in ctx.store.list_tasks(target)
        ]

    @router.get("/api/tasks/{task_id}")
    def task_detail(task_id: str) -> dict[str, Any]:
        return build_task_detail(ctx, task_id)

    @router.get("/api/tasks/{task_id}/events")
    async def task_events(task_id: str, after_seq: int = 0):
        return StreamingResponse(
            event_stream(ctx.store, task_id, after_seq),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.post("/api/tasks/{task_id}/approval")
    def approve(task_id: str, payload: ApprovalRequest) -> dict[str, Any]:
        record = ctx.store.get_task(task_id)
        if record.state is not TaskState.AWAITING_APPROVAL:
            raise HTTPException(status_code=409, detail="任务当前不在等待审批状态")
        # 审批决策事件由状态机统一写（唯一来源），这里只负责把决策交给流程续跑。
        # 早期两处各写一条，时间线上会出现两行一模一样的"审批通过"。
        ctx.runner.resume(
            task_id, payload.decision, payload.operator, payload.reason, source="web"
        )
        return build_task_detail(ctx, task_id)

    @router.post("/api/tasks/{task_id}/clarification")
    def clarify(task_id: str, payload: ClarificationRequest) -> dict[str, Any]:
        record = ctx.store.get_task(task_id)
        if record.state is not TaskState.AWAITING_CLARIFICATION:
            raise HTTPException(status_code=409, detail="任务当前不需要补充信息")
        ctx.runner.continue_after_clarification(task_id, payload.answer)
        return build_task_detail(ctx, task_id)

    @router.get("/api/tasks/{task_id}/approvals")
    def approvals(task_id: str) -> list[dict[str, Any]]:
        ctx.store.get_task(task_id)  # 任务不存在时抛 404
        return ctx.store.list_approvals(task_id)

    # ---------- 数据台 ----------

    @router.get("/api/suppliers")
    def suppliers() -> list[dict[str, Any]]:
        today = __import__("datetime").date.today()
        rows = []
        for supplier in ctx.repo.list_suppliers():
            quals = ctx.repo.list_qualifications(supplier.id)
            nearest = min((q.expires_at for q in quals), default=None)
            rows.append(
                {
                    "id": supplier.id,
                    "code": supplier.code,
                    "name": supplier.name,
                    "tier": supplier.tier,
                    "blacklisted": bool(supplier.blacklisted),
                    "delivery_rate": supplier.delivery_rate,
                    "qualification_count": len(quals),
                    "expires_at": nearest.isoformat() if nearest else None,
                    "expiring_soon": bool(nearest and (nearest - today).days < ctx.config.freshness_warn_days),
                }
            )
        return rows

    @router.get("/api/materials")
    def materials() -> list[dict[str, Any]]:
        """主数据里的可采购物料，供点选式下单表单使用。"""
        return [
            {
                "id": material.id,
                "sku": material.sku,
                "name": material.name,
                "spec": material.spec,
                "unit": material.unit,
                "category": material.category,
            }
            for material in ctx.repo.list_materials()
        ]

    @router.get("/api/cost-centers")
    def cost_centers() -> list[dict[str, str]]:
        """可选成本中心。演示数据固定，真实系统中来自 ERP 主数据。"""
        return [
            {"code": "CC-1001", "name": "行政后勤"},
            {"code": "CC-2003", "name": "门诊部"},
            {"code": "CC-3007", "name": "手术室"},
            {"code": "CC-1002", "name": "护理部"},
        ]

    @router.get("/api/quotes")
    def quotes(material_id: int | None = None) -> list[dict[str, Any]]:
        """报价查询。不传 material_id 时返回全部物料，便于横向比价。"""
        if material_id is not None:
            target = ctx.repo.get_material(material_id)
            materials = [target] if target else []
        else:
            materials = ctx.repo.list_materials()
        suppliers = {s.id: s for s in ctx.repo.list_suppliers()}
        rows: list[dict[str, Any]] = []
        for material in materials:
            for quote in ctx.repo.list_quotes(material.id):
                if quote.supplier_id not in suppliers:
                    continue
                rows.append(
                    {
                        "material_id": material.id,
                        "material_name": material.name,
                        "unit": material.unit,
                        "supplier_code": suppliers[quote.supplier_id].code,
                        "supplier_name": suppliers[quote.supplier_id].name,
                        "unit_price": quote.unit_price,
                        "freight": quote.freight,
                        "lead_days": quote.lead_days,
                    }
                )
        return rows

    @router.get("/api/orders")
    def orders() -> list[dict[str, Any]]:
        suppliers = {s.id: s for s in ctx.repo.list_suppliers()}
        # 物料名必须覆盖全部主数据：早期这里只放了"一次性无菌注射器"一条，
        # 多物料订单里第二种物料会退化成打印物料 ID（页面上显示成"2"）。
        materials = {m.id: m for m in ctx.repo.list_materials()}
        return [
            {
                "id": order.id,
                "task_id": order.task_id,
                "supplier_name": suppliers[order.supplier_id].name
                if order.supplier_id in suppliers
                else str(order.supplier_id),
                "material_name": materials[order.material_id].name
                if order.material_id in materials
                else str(order.material_id),
                "quantity": order.quantity,
                "unit_price": order.unit_price,
                "total_amount": order.total_amount,
                "lead_days": order.lead_days,
                "cost_center": order.cost_center,
                "status": order.status,
                "created_at": order.created_at,
            }
            for order in ctx.repo.list_orders()
        ]

    @router.get("/api/faults")
    def get_faults() -> dict[str, Any]:
        flags = ctx.faults.list_flags()
        return {
            "flags": [
                {"flag": flag, "label": FLAG_LABELS.get(flag, flag), "enabled": flags.get(flag, False)}
                for flag in ALL_FLAGS
            ]
        }

    @router.post("/api/faults")
    def set_fault(payload: FaultRequest = Body(...)) -> dict[str, Any]:
        ctx.faults.set(payload.flag, payload.enabled)
        return get_faults()

    # ---------- 评测 ----------

    @router.post("/api/eval/run")
    def run_eval() -> dict[str, Any]:
        if ctx.eval_runner is None:
            raise HTTPException(status_code=503, detail="评测运行器未配置")
        ctx.eval_runner.start()
        return {"status": ctx.eval_runner.status()}

    @router.get("/api/eval/latest")
    def latest_eval() -> dict[str, Any]:
        if ctx.eval_runner is None:
            raise HTTPException(status_code=503, detail="评测运行器未配置")
        return ctx.eval_runner.latest()

    return router


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
