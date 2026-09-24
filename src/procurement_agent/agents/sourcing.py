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
    min_order_qty: int = 1
    meets_moq: bool = True
    remaining_shelf_life_days: int | None = None
    shelf_life_ok: bool = True
    tier: str = ""


def _has_defect(item: QuoteComparison) -> bool:
    """报价是否存在硬伤：资质临期 / 交期不满足 / 效期不足 / 未达起订量。"""
    return bool(
        item.expiring_soon or not item.on_time or not item.shelf_life_ok or not item.meets_moq
    )


def _prefer_tier(
    comparisons: list[QuoteComparison],
    recommended: QuoteComparison,
    config: ProcurementConfig,
) -> QuoteComparison | None:
    """成本相近时按配置的供应商等级改选；不该改选时返回 None。

    只在"双方都没有硬伤"且综合成本差异不超过容忍比例时生效——偏好是弱偏好，
    不允许压过价格（否则"优先 A 类"会变成"只买 A 类"，比价就失去意义）。
    """
    prefer_tier = (getattr(config, "prefer_tier", "") or "").upper()
    tolerance = getattr(config, "tier_preference_tolerance", 0.0) or 0.0
    if not prefer_tier or tolerance <= 0 or recommended.tier == prefer_tier:
        return None
    if _has_defect(recommended):
        return None
    band = recommended.total * (1 + tolerance)
    candidates = [
        item
        for item in comparisons
        if item.tier == prefer_tier and item.total <= band and not _has_defect(item)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda item: item.total)


def _defect_cause(
    item: QuoteComparison,
    available_days: int | None,
    material_shelf_life: int | None,
    min_ratio: float,
) -> str | None:
    """最低价未被选中时，给出它自身的硬伤原因；没有硬伤返回 None。"""
    if item.expiring_soon:
        return f"{item.name} 资质临期"
    if not item.on_time:
        return f"{item.name} 交期 {item.lead_days} 天，无法在 {available_days} 天内到货"
    if not item.shelf_life_ok:
        required = int(material_shelf_life * min_ratio) if material_shelf_life else 0
        return (
            f"{item.name} 该批次剩余效期 {item.remaining_shelf_life_days} 天，"
            f"低于要求的 {required} 天"
        )
    if not item.meets_moq:
        return f"{item.name} 起订量 {item.min_order_qty}，本次采购量未达标"
    return None


@dataclass
class SourcingOutcome:
    comparisons: list[QuoteComparison] = field(default_factory=list)
    recommended: QuoteComparison | None = None
    reason: str = ""
    insufficient_quotes: bool = False
    available_days: int | None = None
    deadline_feasible: bool = True
    moq_violated: bool = False
    shelf_life_insufficient: bool = False


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

    # 效期要求来自物料：到货时剩余效期不得低于总效期的固定比例
    material = repo.get_material(material_id)
    material_shelf_life = getattr(material, "shelf_life_days", None)
    min_ratio = float(getattr(material, "min_remaining_ratio", 0.66) or 0.66)

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
        moq = int(quote.min_order_qty or 1)
        shelf_life_ok = True
        if material_shelf_life and quote.remaining_shelf_life_days is not None:
            shelf_life_ok = quote.remaining_shelf_life_days >= material_shelf_life * min_ratio
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
                min_order_qty=moq,
                meets_moq=quantity >= moq,
                remaining_shelf_life_days=quote.remaining_shelf_life_days,
                shelf_life_ok=shelf_life_ok,
                tier=getattr(supplier, "tier", "") or "",
            )
        )

    outcome = SourcingOutcome(comparisons=comparisons)
    outcome.available_days = available_days
    outcome.insufficient_quotes = len(comparisons) < config.min_quote_count

    if not comparisons:
        outcome.reason = "没有可用报价，无法比价"
        return outcome

    cheapest = min(comparisons, key=lambda item: item.total)
    # 推荐排序：资质临期 → 交期不满足 → 效期不足 → 未达起订量 → 综合成本。
    # 布尔值排序天然"先排除有问题的项"，全部满足时再按价格选。
    recommended = min(
        comparisons,
        key=lambda item: (
            item.expiring_soon,
            not item.on_time,
            not item.shelf_life_ok,
            not item.meets_moq,
            item.total,
        ),
    )
    # 采购偏好：按供应商等级做"成本相近时优先"的改选，理由写进比价结论
    prefer_reason: str | None = None
    tier_pick = _prefer_tier(comparisons, recommended, config)
    if tier_pick is not None:
        prefer_reason = (
            f"{tier_pick.name}（{tier_pick.tier} 类）综合成本 ¥{tier_pick.total:.2f} "
            f"与 {recommended.name} 的 ¥{recommended.total:.2f} 接近，"
            f"按采购偏好优先 {config.prefer_tier} 类供应商"
        )
        recommended = tier_pick
    outcome.recommended = recommended
    outcome.deadline_feasible = bool(recommended.on_time)
    outcome.moq_violated = not recommended.meets_moq
    outcome.shelf_life_insufficient = not recommended.shelf_life_ok

    if recommended.total > cheapest.total:
        defect = _defect_cause(cheapest, available_days, material_shelf_life, min_ratio)
        # 可能是多条原因叠加：最低价本身有硬伤，且改选还叠加了供应商等级偏好
        if prefer_reason is not None:
            cause = f"{defect}；{prefer_reason}" if defect else prefer_reason
        elif defect:
            cause = defect
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
    if available_days is None and outcome.shelf_life_insufficient:
        outcome.reason += (
            f"；注意：所选供应商该批次剩余效期"
            f"{recommended.remaining_shelf_life_days} 天，低于效期要求"
        )
    return outcome
