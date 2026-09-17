from __future__ import annotations

from dataclasses import dataclass

from procurement_agent.agents.sourcing import SourcingOutcome
from procurement_agent.erp.repository import ErpRepository
from procurement_agent.sandbox.policy import PolicyDecision, PolicyEngine
from procurement_agent.skills_loader import SkillRegistry


class InsufficientQuotesError(Exception):
    def __init__(self, message: str = "可用报价不足，无法生成订单") -> None:
        super().__init__(message)


@dataclass(frozen=True)
class OrderDraft:
    task_id: str
    supplier_id: int
    material_id: int
    quantity: int
    unit_price: float
    total_amount: float
    lead_days: int
    cost_center: str | None = None
    supplier_expiring_soon: bool = False
    price_gap_ratio: float = 0.0
    supplier_name: str = ""
    insufficient_quotes: bool = False
    deadline_infeasible: bool = False


def run_ordering(
    repo: ErpRepository,
    policy: PolicyEngine,
    sourcing: SourcingOutcome,
    material_id: int,
    quantity: int,
    cost_center: str,
    task_id: str,
    *,
    skills: SkillRegistry | None = None,
) -> tuple[OrderDraft, PolicyDecision]:
    """由比价结论生成订单草稿并交给策略引擎判定。此函数不写库。"""
    del repo  # 保留参数以与其他子 Agent 保持统一签名
    if skills is not None:
        skills.load("order_compliance")

    recommended = sourcing.recommended
    if recommended is None:
        raise InsufficientQuotesError()

    total_amount = round(recommended.unit_price * quantity + recommended.freight, 2)
    cheapest = min(
        sourcing.comparisons,
        key=lambda item: round(item.unit_price * quantity + item.freight, 2),
    )
    cheapest_total = round(cheapest.unit_price * quantity + cheapest.freight, 2)
    price_gap_ratio = 0.0
    if cheapest_total > 0 and recommended.supplier_id != cheapest.supplier_id:
        price_gap_ratio = (total_amount - cheapest_total) / cheapest_total

    draft = OrderDraft(
        task_id=task_id,
        supplier_id=recommended.supplier_id,
        material_id=material_id,
        quantity=quantity,
        unit_price=recommended.unit_price,
        total_amount=total_amount,
        lead_days=recommended.lead_days,
        cost_center=cost_center,
        supplier_expiring_soon=recommended.expiring_soon,
        price_gap_ratio=max(price_gap_ratio, 0.0),
        supplier_name=recommended.name,
        insufficient_quotes=bool(sourcing.insufficient_quotes),
        deadline_infeasible=not sourcing.deadline_feasible,
    )
    return draft, policy.check_order(draft)
