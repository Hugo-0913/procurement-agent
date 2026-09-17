from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from procurement_agent.config import ProcurementConfig

PRICE_GAP_THRESHOLD = 0.10


class OrderDraftLike(Protocol):
    total_amount: float
    supplier_expiring_soon: bool
    price_gap_ratio: float
    insufficient_quotes: bool


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool = True
    requires_approval: bool = False
    matched_rules: tuple[str, ...] = ()
    reason: str = ""


@dataclass
class PolicyEngine:
    """沙箱层一：敏感操作策略校验。金额阈值来自配置，不硬编码。"""

    config: ProcurementConfig
    extra_rules: tuple[str, ...] = field(default=())

    def check_order(self, draft: OrderDraftLike) -> PolicyDecision:
        matched: list[str] = []
        if draft.total_amount > self.config.approval_threshold:
            matched.append(
                f"订单金额 ¥{draft.total_amount:.2f} > 阈值 "
                f"¥{self.config.approval_threshold:.2f}"
            )
        if draft.supplier_expiring_soon:
            matched.append("供应商资质临期，需要人工确认")
        if draft.price_gap_ratio > PRICE_GAP_THRESHOLD:
            matched.append(
                f"推荐结果非最低价，差额比例 {draft.price_gap_ratio:.1%} 超过 10%"
            )
        if draft.insufficient_quotes:
            matched.append("可用报价不足，无法完成比价，需人工确认")

        if not matched:
            return PolicyDecision(allowed=True, requires_approval=False)
        return PolicyDecision(
            allowed=True,
            requires_approval=True,
            matched_rules=tuple(matched),
            reason="；".join(matched),
        )
