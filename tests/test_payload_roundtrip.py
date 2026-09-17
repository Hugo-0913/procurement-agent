"""payload 往返测试。

历史缺陷：`sourcing_to_payload` 早期是手写字典，新增字段（可用天数、交期是否可满足）
没有同步进去，导致下游从 payload 重建对象时又变回默认值，交期校验静默失效。
这里对每个领域对象的往返做断言，防止同类问题再次发生。
"""

from procurement_agent.agents.payloads import (
    qualification_from_payload,
    qualification_to_payload,
    sourcing_from_payload,
    sourcing_to_payload,
)
from procurement_agent.agents.qualification import (
    QualificationOutcome,
    QualifiedSupplier,
    RejectedSupplier,
)
from procurement_agent.agents.sourcing import QuoteComparison, SourcingOutcome


def make_comparison(**overrides) -> QuoteComparison:
    base = dict(
        supplier_id=1,
        code="SUP-A",
        name="晨光办公用品",
        unit_price=21.5,
        freight=0.0,
        lead_days=3,
        total=1075.0,
        history_avg=21.5,
        deviation=0.0,
        expiring_soon=False,
        on_time=True,
    )
    base.update(overrides)
    return QuoteComparison(**base)


def test_sourcing_roundtrip_keeps_deadline_fields():
    outcome = SourcingOutcome(
        comparisons=[make_comparison(on_time=False)],
        recommended=make_comparison(on_time=False),
        reason="交期无法满足",
        insufficient_quotes=True,
        available_days=1,
        deadline_feasible=False,
    )
    restored = sourcing_from_payload(sourcing_to_payload(outcome))
    assert restored.available_days == 1
    assert restored.deadline_feasible is False
    assert restored.comparisons[0].on_time is False
    assert restored.insufficient_quotes is True


def test_qualification_roundtrip():
    outcome = QualificationOutcome(
        qualified=[
            QualifiedSupplier(1, "SUP-A", "晨光办公用品", "A", False),
        ],
        rejected=[RejectedSupplier(4, "SUP-D", "廉价办公仓", "命中黑名单，禁止参与采购")],
        notes=["金辉文具 资质临期"],
    )
    restored = qualification_from_payload(qualification_to_payload(outcome))
    assert restored.qualified[0].code == "SUP-A"
    assert restored.rejected[0].reason.startswith("命中黑名单")
    assert restored.notes == ["金辉文具 资质临期"]

