"""Assign shortage priority with fixed, testable Python rules."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class PriorityDecision:
    """Priority-rule output."""

    priority: str
    rule_id: str
    explanation: str


def determine_priority(
    shortage_quantity: float,
    planned_start_date: date,
    analysis_date: date,
    latest_required_receipt_date: date | None = None,
    data_error: bool = False,
) -> PriorityDecision:
    """Determine priority from shortage, start timing, and required receipts."""

    if data_error:
        return PriorityDecision(
            "Data Error",
            "P0",
            "A data error prevents reliable calculation.",
        )
    days_until_start = (planned_start_date - analysis_date).days
    if shortage_quantity > 0 and days_until_start <= 2:
        return PriorityDecision(
            "Critical",
            "P1",
            "A shortage exists and production starts within two days or is overdue.",
        )
    if shortage_quantity > 0 and days_until_start <= 7:
        return PriorityDecision(
            "High",
            "P2",
            "A shortage exists and production starts in three to seven days.",
        )
    if shortage_quantity > 0:
        return PriorityDecision(
            "Medium",
            "P3A",
            "A shortage exists and production starts in more than seven days.",
        )
    if latest_required_receipt_date is not None and (planned_start_date - latest_required_receipt_date).days <= 1:
        return PriorityDecision(
            "Medium",
            "P3B",
            "Supply is sufficient but depends on a receipt arriving within one day of production start.",
        )
    return PriorityDecision(
        "Low",
        "P4",
        "No shortage exists and supply does not depend on a near-start required receipt.",
    )
