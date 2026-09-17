from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from procurement_agent.agents.qualification import QualificationOutcome
from procurement_agent.config import ProcurementConfig
from procurement_agent.erp.repository import ErpRepository
from procurement_agent.skills_loader import SkillRegistry


@dataclass(frozen=True)
class QuoteComparison:
    supplier_id: int
    code: str
    name: str
    unit_price: float
    freight: float
    lead_days: int
    total: float
    history_avg: float | None
    deviation: float | None
    expiring_soon: bool
    on_time: bool = True


@dataclass
class SourcingOutcome:
    comparisons: list[QuoteComparison] = field(default_factory=list)
    recommended: QuoteComparison | None = None
    reason: str = ""
    insufficient_quotes: bool = False
    available_days: int | None = None
    deadline_feasible: bool = True


def run_sourcing(
    repo: ErpRepository,
    config: ProcurementConfig,
    material_id: int,
    quantity: int,
    qualified: QualificationOutcome,
    *,
    expected_date: str | None = None,
    skills: SkillRegistry | None = None,
) -> SourcingOutcome:
    """确定性比价：综合成本 = 单价 × 数量 + 运费。"""
    if skills is not None:
        skills.load("price_comparison")

    qualified_map = {item.supplier_id: item for item in qualified.qualified}
    comparisons: list[QuoteComparison] = []

    # 期望到货日期决定可用天数；未指定日期时不校验交期
    available_days: int | None = None
    if expected_date:
        try:
            available_days = (date.fromisoformat(str(expected_date)) - date.today()).days
        except ValueError:
            available_days = None

    for quote in repo.list_quotes(material_id):
        supplier = qualified_map.get(quote.supplier_id)
        if supplier is None:
            continue
        history = repo.price_history(material_id, quote.supplier_id)
        history_avg = sum(history) / len(history) if history else None
        deviation = (
            (quote.unit_price - history_avg) / history_avg if history_avg else None
        )
        total = round(quote.unit_price * quantity + quote.freight, 2)
        comparisons.append(
            QuoteComparison(
                supplier_id=quote.supplier_id,
                code=supplier.code,
                name=supplier.name,
                unit_price=quote.unit_price,
                freight=quote.freight,
                lead_days=quote.lead_days,
                total=total,
                history_avg=history_avg,
                deviation=deviation,
                expiring_soon=supplier.expiring_soon,
                on_time=available_days is None or quote.lead_days <= available_days,
            )
        )

    outcome = SourcingOutcome(comparisons=comparisons)
    outcome.available_days = available_days
    outcome.insufficient_quotes = len(comparisons) < config.min_quote_count

    if not comparisons:
        outcome.reason = "没有可用报价，无法比价"
        return outcome

    cheapest = min(comparisons, key=lambda item: item.total)
    eligible = [item for item in comparisons if not item.expiring_soon]
    # 交期无法满足的供应商优先排除；若全部不满足，则保留并标记为需要人工确认
    on_time = [item for item in eligible if item.on_time]
    candidates = on_time or eligible or comparisons
    recommended = min(candidates, key=lambda item: item.total)
    outcome.recommended = recommended
    outcome.deadline_feasible = bool(recommended.on_time)

    if recommended.total > cheapest.total:
        if cheapest.expiring_soon:
            cause = f"{cheapest.name} 资质临期"
        elif not cheapest.on_time:
            cause = f"{cheapest.name} 交期 {cheapest.lead_days} 天，无法在 {available_days} 天内到货"
        else:
            cause = "综合成本口径差异"
        outcome.reason = (
            f"推荐 {recommended.name}，综合成本 ¥{recommended.total:.2f}；"
            f"未选最低价 {cheapest.name}，原因：{cause}"
        )
    else:
        outcome.reason = (
            f"推荐 {recommended.name}，综合成本最低 ¥{recommended.total:.2f}"
        )

    if available_days is not None and not outcome.deadline_feasible:
        outcome.reason += (
            f"；注意：期望 {available_days} 天内到货，所有可用供应商交期均无法满足"
            f"（最快 {min(item.lead_days for item in comparisons)} 天）"
        )
    return outcome
