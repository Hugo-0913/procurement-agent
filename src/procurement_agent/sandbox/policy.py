from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence

from procurement_agent.config import ProcurementConfig

PRICE_GAP_THRESHOLD = 0.10


class OrderDraftLike(Protocol):
    total_amount: float
    supplier_expiring_soon: bool
    price_gap_ratio: float
    insufficient_quotes: bool
    deadline_infeasible: bool


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
        """单行订单校验，等价于只含一行的订单。"""
        return self.check_lines([draft])

    def check_lines(self, lines: Sequence[OrderDraftLike]) -> PolicyDecision:
        """按订单行集合校验。

        多物料采购会产生多行，规则口径如下：
        - 金额：按**合计金额**与阈值比较，而不是逐行比较；
        - 临期 / 交期 / 报价不足：任一行命中即需人工确认；
        - 非最低价：任一行差额超过阈值即需人工确认。
        """
        if not lines:
            return PolicyDecision(allowed=True, requires_approval=False)

        matched: list[str] = []
        total_amount = sum(line.total_amount for line in lines)
        if total_amount > self.config.approval_threshold:
            matched.append(
                f"订单金额 ¥{total_amount:.2f} > 阈值 "
                f"¥{self.config.approval_threshold:.2f}"
            )
        if any(line.supplier_expiring_soon for line in lines):
            matched.append("供应商资质临期，需要人工确认")
        worst_gap = max((line.price_gap_ratio for line in lines), default=0.0)
        if worst_gap > PRICE_GAP_THRESHOLD:
            matched.append(
                f"推荐结果非最低价，差额比例 {worst_gap:.1%} 超过 10%"
            )
        if any(line.insufficient_quotes for line in lines):
            matched.append("可用报价不足，无法完成比价，需人工确认")
        if any(line.deadline_infeasible for line in lines):
            matched.append("交期无法满足期望到货日期，需人工确认")

        if not matched:
            return PolicyDecision(allowed=True, requires_approval=False)
        return PolicyDecision(
            allowed=True,
            requires_approval=True,
            matched_rules=tuple(matched),
            reason="；".join(matched),
        )
