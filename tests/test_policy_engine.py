from procurement_agent.agents.ordering import OrderDraft
from procurement_agent.config import ProcurementConfig
from procurement_agent.sandbox.policy import PolicyEngine

CFG = ProcurementConfig(50000.0, 3, 12000, 2, 30)


def make_draft(total: float, expiring: bool = False, price_gap: float = 0.0) -> OrderDraft:
    return OrderDraft(
        task_id="t-1",
        supplier_id=1,
        material_id=1,
        quantity=50,
        unit_price=total / 50,
        total_amount=total,
        lead_days=3,
        cost_center="CC-1001",
        supplier_expiring_soon=expiring,
        price_gap_ratio=price_gap,
    )


def test_amount_below_threshold_allows():
    decision = PolicyEngine(CFG).check_order(make_draft(1000.0))
    assert decision.allowed is True
    assert decision.requires_approval is False
    assert decision.matched_rules == ()


def test_amount_above_threshold_requires_approval():
    decision = PolicyEngine(CFG).check_order(make_draft(62400.0))
    assert decision.requires_approval is True
    assert any("50000" in rule for rule in decision.matched_rules)
    assert any("62400" in rule for rule in decision.matched_rules)


def test_expiring_supplier_requires_approval():
    decision = PolicyEngine(CFG).check_order(make_draft(1000.0, expiring=True))
    assert decision.requires_approval is True
    assert any("临期" in rule for rule in decision.matched_rules)


def test_price_gap_requires_approval():
    decision = PolicyEngine(CFG).check_order(make_draft(1000.0, price_gap=0.15))
    assert decision.requires_approval is True
    assert any("非最低价" in rule for rule in decision.matched_rules)


def test_multiple_rules_accumulate():
    decision = PolicyEngine(CFG).check_order(
        make_draft(62400.0, expiring=True, price_gap=0.2)
    )
    assert len(decision.matched_rules) == 3
    assert decision.reason.count("；") == 2


def test_threshold_comes_from_config():
    strict = ProcurementConfig(100.0, 3, 12000, 2, 30)
    decision = PolicyEngine(strict).check_order(make_draft(200.0))
    assert decision.requires_approval is True


def test_insufficient_quotes_requires_approval():
    """只剩一家可用报价时不能静默下单，必须转人工确认。"""
    draft = OrderDraft(
        task_id="t-1",
        supplier_id=1,
        material_id=1,
        quantity=50,
        unit_price=21.5,
        total_amount=1075.0,
        lead_days=3,
        cost_center="CC-1001",
        insufficient_quotes=True,
    )
    decision = PolicyEngine(CFG).check_order(draft)
    assert decision.requires_approval is True
    assert any("报价不足" in rule for rule in decision.matched_rules)


def test_infeasible_deadline_requires_approval():
    """交期无法满足期望到货日期时必须转人工，不能静默下单。"""
    draft = OrderDraft(
        task_id="t-1",
        supplier_id=1,
        material_id=1,
        quantity=50,
        unit_price=21.5,
        total_amount=1075.0,
        lead_days=3,
        cost_center="CC-1001",
        deadline_infeasible=True,
    )
    decision = PolicyEngine(CFG).check_order(draft)
    assert decision.requires_approval is True
    assert any("交期" in rule for rule in decision.matched_rules)
