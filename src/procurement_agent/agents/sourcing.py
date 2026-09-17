from __future__ import annotations

from dataclasses import dataclass, field

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


@dataclass
class SourcingOutcome:
    comparisons: list[QuoteComparison] = field(default_factory=list)
    recommended: QuoteComparison | None = None
    reason: str = ""
    insufficient_quotes: bool = False


def run_sourcing(
    repo: ErpRepository,
    config: ProcurementConfig,
    material_id: int,
    quantity: int,
    qualified: QualificationOutcome,
    *,
    skills: SkillRegistry | None = None,
) -> SourcingOutcome:
    """确定性比价：综合成本 = 单价 × 数量 + 运费。"""
    if skills is not None:
        skills.load("price_comparison")

    qualified_map = {item.supplier_id: item for item in qualified.qualified}
    comparisons: list[QuoteComparison] = []

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
            )
        )

    outcome = SourcingOutcome(comparisons=comparisons)
    outcome.insufficient_quotes = len(comparisons) < config.min_quote_count

    if not comparisons:
        outcome.reason = "没有可用报价，无法比价"
        return outcome

    cheapest = min(comparisons, key=lambda item: item.total)
    eligible = [item for item in comparisons if not item.expiring_soon]
    candidates = eligible or comparisons
    recommended = min(candidates, key=lambda item: item.total)
    outcome.recommended = recommended

    if recommended.total > cheapest.total:
        cause = (
            f"{cheapest.name} 资质临期"
            if cheapest.expiring_soon
            else "综合成本口径差异"
        )
        outcome.reason = (
            f"推荐 {recommended.name}，综合成本 ¥{recommended.total:.2f}；"
            f"未选最低价 {cheapest.name}，原因：{cause}"
        )
    else:
        outcome.reason = (
            f"推荐 {recommended.name}，综合成本最低 ¥{recommended.total:.2f}"
        )
    return outcome

