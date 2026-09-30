"""Prototype in-session workflow state, isolated from calculations."""

from __future__ import annotations

import pandas as pd

WORKFLOW_STATUSES = (
    "NEW", "IN_REVIEW", "WAITING_FOR_PROCUREMENT", "WAITING_FOR_PRODUCTION_PLANNING",
    "WAITING_FOR_MATERIAL_PLANNING", "RESOLVED", "DISMISSED",
)


def apply_workflow_state(exceptions: pd.DataFrame, state: dict[str, str]) -> pd.DataFrame:
    output = exceptions.copy()
    if output.empty:
        return output
    output["Workflow_Status"] = output["Exception_ID"].map(state).fillna("NEW")
    return output


def update_workflow_state(state: dict[str, str], exception_id: str, status: str) -> None:
    if status not in WORKFLOW_STATUSES:
        raise ValueError(f"Unsupported workflow status: {status}")
    state[exception_id] = status
