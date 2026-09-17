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
    return {
        "comparisons": [asdict(item) for item in outcome.comparisons],
        "recommended": asdict(outcome.recommended) if outcome.recommended else None,
        "reason": outcome.reason,
        "insufficient_quotes": outcome.insufficient_quotes,
    }


def sourcing_from_payload(data: dict) -> SourcingOutcome:
    recommended = data.get("recommended")
    return SourcingOutcome(
        comparisons=[QuoteComparison(**item) for item in data.get("comparisons", [])],
        recommended=QuoteComparison(**recommended) if recommended else None,
        reason=data.get("reason", ""),
        insufficient_quotes=bool(data.get("insufficient_quotes", False)),
    )


def draft_to_payload(draft: OrderDraft) -> dict:
    return asdict(draft)


def payload_to_draft(data: dict) -> OrderDraft:
    return OrderDraft(**data)

