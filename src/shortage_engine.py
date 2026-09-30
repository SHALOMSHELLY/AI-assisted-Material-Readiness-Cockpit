"""Orchestrate deterministic demand, supply, shortage, and priority calculation."""

from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from src.bom import build_material_requirements
from src.data_models import ValidationReport
from src.incoming_supply import build_incoming_receipts, matching_receipts
from src.inventory import build_inventory_pools
from src.priority_rules import determine_priority
from src.validators import validate_workbook


class AnalysisBlockedError(Exception):
    """Block analysis when Data Errors exist."""

    def __init__(self, report: ValidationReport):
        super().__init__("Workbook validation contains Data Errors.")
        self.report = report


@dataclass
class AnalysisResult:
    """Hold validation, demand, and allocation audit results."""

    validation_report: ValidationReport
    material_requirements: pd.DataFrame
    shortage_results: pd.DataFrame


def run_shortage_analysis(
    sheets: dict[str, pd.DataFrame], analysis_date: date,
    validation_report: ValidationReport | None = None,
) -> AnalysisResult:
    """Run deterministic shortage analysis.

    Identical inputs and analysis dates use the same sorting and rules and
    therefore produce identical results.
    """

    report = validation_report if validation_report is not None else validate_workbook(sheets, analysis_date)
    if not report.is_valid:
        raise AnalysisBlockedError(report)

    requirements = build_material_requirements(sheets["Production_Orders"], sheets["BOM"])
    if requirements.empty:
        return AnalysisResult(report, requirements, pd.DataFrame())

    inventory_pools = build_inventory_pools(sheets["Inventory"])
    receipts = build_incoming_receipts(sheets["Incoming_PO"], analysis_date)
    receipt_states: dict[tuple[str, str, str], dict[str, Any]] = {}
    requirements = requirements.sort_values(
        ["Material_Need_Date", "Production_Order_ID", "Production_Order_Item", "Material_ID"],
        kind="stable",
    ).reset_index(drop=True)

    results: list[dict[str, Any]] = []
    for sequence, (_, demand) in enumerate(requirements.iterrows(), start=1):
        key = (demand["Material_ID"], demand["Plant"], demand["Quantity_Unit"])
        pool = inventory_pools.get(
            key,
            {
                "Unrestricted_Inventory": 0.0,
                "Safety_Stock": 0.0,
                "Usable_Inventory": 0.0,
                "Remaining_Inventory": 0.0,
            },
        )
        required = float(demand["Required_Quantity"])
        inventory_before = float(pool["Remaining_Inventory"])
        inventory_allocated = min(required, inventory_before)
        pool["Remaining_Inventory"] = inventory_before - inventory_allocated
        remaining_need = required - inventory_allocated

        material_receipts = matching_receipts(receipts, key)
        state = receipt_states.get(key)
        if state is None:
            first_current = next((index for index, row in enumerate(material_receipts) if not row["Is_Overdue"]), len(material_receipts))
            state = {
                "next_index": first_current, "allocation_index": first_current,
                "available_eligible": 0.0,
                "remaining_nonoverdue": sum(row["Remaining_Open_Quantity"] for row in material_receipts[first_current:]),
            }
            receipt_states[key] = state
        overdue = material_receipts[:state["allocation_index"]]
        overdue = [row for row in overdue if row["Is_Overdue"]]
        overdue_quantity = sum(row["Remaining_Open_Quantity"] for row in overdue)
        overdue_lines = [
            f"{row['PO_ID']}/{row['PO_Item']}/{row['Schedule_Line']}:{row['Remaining_Open_Quantity']:g}"
            for row in overdue
        ]
        while (state["next_index"] < len(material_receipts)
               and material_receipts[state["next_index"]]["Expected_Receipt_Date"] <= demand["Material_Need_Date"]):
            state["available_eligible"] += material_receipts[state["next_index"]]["Remaining_Open_Quantity"]
            state["next_index"] += 1
        eligible_before = state["available_eligible"]
        po_allocated = 0.0
        po_details: list[str] = []
        allocated_dates: list[date] = []
        while remaining_need > 0 and state["allocation_index"] < state["next_index"]:
            receipt = material_receipts[state["allocation_index"]]
            quantity = min(remaining_need, receipt["Remaining_Open_Quantity"])
            if quantity <= 0:
                state["allocation_index"] += 1
                continue
            receipt["Remaining_Open_Quantity"] -= quantity
            remaining_need -= quantity
            po_allocated += quantity
            state["available_eligible"] -= quantity
            state["remaining_nonoverdue"] -= quantity
            allocated_dates.append(receipt["Expected_Receipt_Date"])
            po_details.append(
                f"{receipt['PO_ID']}/{receipt['PO_Item']}/{receipt['Schedule_Line']}:{quantity:g}"
            )
            if receipt["Remaining_Open_Quantity"] <= 0:
                state["allocation_index"] += 1

        shortage = max(0.0, remaining_need)
        late_quantity = state["remaining_nonoverdue"] - state["available_eligible"]
        if state["allocation_index"] < state["next_index"]:
            next_receipt = material_receipts[state["allocation_index"]]["Expected_Receipt_Date"]
        elif state["next_index"] < len(material_receipts):
            next_receipt = material_receipts[state["next_index"]]["Expected_Receipt_Date"]
        else:
            next_receipt = None
        latest_required_receipt = max(allocated_dates, default=None)
        priority = determine_priority(
            shortage,
            demand["Material_Need_Date"],
            analysis_date,
            latest_required_receipt,
        )
        total_allocated = inventory_allocated + po_allocated
        total_available_before = inventory_before + eligible_before
        explanation = (
            f" Requirement {required:g} {demand['Quantity_Unit']}; remaining usable inventory before allocation "
            f"{inventory_before:g}, inventory allocated {inventory_allocated:g}; remaining eligible PO supply before the need date "
            f"{eligible_before:g}, PO supply allocated {po_allocated:g}; shortage {shortage:g}."
        )
        results.append(
            {
                "Analysis_Date": analysis_date,
                **demand.to_dict(),
                "Unrestricted_Inventory": pool["Unrestricted_Inventory"],
                "Safety_Stock": pool["Safety_Stock"],
                "Usable_Inventory": pool["Usable_Inventory"],
                "Inventory_Available_Before_Allocation": inventory_before,
                "Eligible_Incoming_Quantity": eligible_before,
                "Late_Incoming_Quantity": late_quantity,
                "Overdue_Incoming_Quantity": overdue_quantity,
                "Overdue_PO_Lines": ", ".join(overdue_lines),
                "Total_Available": total_available_before,
                "Inventory_Allocated": inventory_allocated,
                "Incoming_PO_Allocated": po_allocated,
                "Total_Available_Allocated": total_allocated,
                "Shortage_Quantity": shortage,
                "Remaining_Inventory_After_Allocation": pool["Remaining_Inventory"],
                "Next_Receipt_Date": next_receipt,
                "Latest_Required_Receipt_Date": latest_required_receipt,
                "Allocated_PO_Lines": ", ".join(po_details),
                "Allocation_Sequence": sequence,
                "Priority": priority.priority,
                "Priority_Rule_ID": priority.rule_id,
                "Priority_Explanation": priority.explanation,
                "Calculation_Explanation": explanation,
            }
        )
        inventory_pools[key] = pool
    return AnalysisResult(report, requirements, pd.DataFrame(results))
