from __future__ import annotations

from dataclasses import asdict

from procurement_agent.agents.ordering import OrderDraft
from procurement_agent.agents.qualification import (
    QualificationOutcome,
    QualifiedSupplier,
    RejectedSupplier,
)
from procurement_agent.agents.sourcing import QuoteComparison, SourcingOutcome


def qualification_to_payload(outcome: QualificationOutcome) -> dict:
    return {
        "qualified": [asdict(item) for item in outcome.qualified],
        "rejected": [asdict(item) for item in outcome.rejected],
        "notes": list(outcome.notes),
    }


def qualification_from_payload(data: dict) -> QualificationOutcome:
    return QualificationOutcome(
        qualified=[QualifiedSupplier(**item) for item in data.get("qualified", [])],
        rejected=[RejectedSupplier(**item) for item in data.get("rejected", [])],
        notes=list(data.get("notes", [])),
    )


def sourcing_to_payload(outcome: SourcingOutcome) -> dict:
    """比价结果的跨阶段载荷。

    这里必须是**显式全字段**：它是手写字典，漏字段不会报错，只会让字段在
    `sourcing_from_payload` 重建时静默回落成默认值。历史上漏过 available_days /
    deadline_feasible，后来又漏了 moq_violated / shelf_life_insufficient——
    后两个一漏，起订量与效期这两条转人工规则在端到端流程里就再也不触发了。
    `tests/test_payload_roundtrip.py` 用字段集合对齐把它钉住。
    """
    return {
        "comparisons": [asdict(item) for item in outcome.comparisons],
        "recommended": asdict(outcome.recommended) if outcome.recommended else None,
        "reason": outcome.reason,
        "insufficient_quotes": outcome.insufficient_quotes,
        "available_days": outcome.available_days,
        "deadline_feasible": outcome.deadline_feasible,
        "moq_violated": outcome.moq_violated,
        "shelf_life_insufficient": outcome.shelf_life_insufficient,
    }


def sourcing_from_payload(data: dict) -> SourcingOutcome:
    recommended = data.get("recommended")
    return SourcingOutcome(
        comparisons=[QuoteComparison(**item) for item in data.get("comparisons", [])],
        recommended=QuoteComparison(**recommended) if recommended else None,
        reason=data.get("reason", ""),
        insufficient_quotes=bool(data.get("insufficient_quotes", False)),
        available_days=data.get("available_days"),
        deadline_feasible=bool(data.get("deadline_feasible", True)),
        moq_violated=bool(data.get("moq_violated", False)),
        shelf_life_insufficient=bool(data.get("shelf_life_insufficient", False)),
    )


def draft_to_payload(draft: OrderDraft) -> dict:
    return asdict(draft)


def payload_to_draft(data: dict) -> OrderDraft:
    return OrderDraft(**data)


# ---------- 多物料（多订单行）载荷 ----------


def sourcing_items_to_payload(items: list[dict]) -> dict:
    """把多个物料的比价结果合成一份载荷。

    items 中每一项形如 {"material_id", "material_name", "quantity", "outcome"}。
    顶层字段是对所有物料的聚合，便于前端与策略层直接使用。
    """
    details = [sourcing_to_payload(item["outcome"]) for item in items]
    return {
        "items": [
            {
                "material_id": item["material_id"],
                "material_name": item["material_name"],
                "quantity": item["quantity"],
                "detail": detail,
            }
            for item, detail in zip(items, details)
        ],
        "reason": "；".join(detail["reason"] for detail in details if detail["reason"]),
        "insufficient_quotes": any(detail["insufficient_quotes"] for detail in details),
        "deadline_feasible": all(detail["deadline_feasible"] for detail in details),
        "available_days": details[0]["available_days"] if details else None,
    }


def sourcing_items_from_payload(data: dict) -> list[SourcingOutcome]:
    """从载荷还原每个物料的比价结果。兼容旧的单物料载荷。"""
    if "items" not in data:
        return [sourcing_from_payload(data)]
    return [sourcing_from_payload(item["detail"]) for item in data["items"]]
