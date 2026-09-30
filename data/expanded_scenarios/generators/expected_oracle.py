"""Independent expected-result oracle.

This module deliberately imports neither ``src.shortage_engine`` nor any other
production calculation module.  It is a small, transparent reference model
used only to materialize the frozen expected JSON in a future, reviewed step.
It is not invoked by the workbook generator.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from typing import Any

from .common import ANALYSIS_DATE, Scenario


def _priority(shortage: float, start: date, latest_receipt: date | None) -> tuple[str, str]:
    days = (start - ANALYSIS_DATE).days
    if shortage > 0 and days <= 2: return "Critical", "P1"
    if shortage > 0 and days <= 7: return "High", "P2"
    if shortage > 0: return "Medium", "P3A"
    if latest_receipt is not None and (start - latest_receipt).days <= 1: return "Medium", "P3B"
    return "Low", "P4"


def build_full_expected(scenario: Scenario) -> list[dict[str, Any]]:
    """Construct every expected analysis row from documented business rules."""

    active = {"CREATED", "RELEASED", "PARTIALLY_CONFIRMED"}
    boms: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in scenario.sheets["BOM"]:
        boms[(row["Parent_Product_ID"], row["Plant"])].append(row)

    demands: list[dict[str, Any]] = []
    for production in scenario.sheets["Production_Orders"]:
        if production["Order_Status"] not in active or production["Remaining_Quantity"] <= 0:
            continue
        grouped_components: dict[tuple[str, str], float] = defaultdict(float)
        components = boms[(production["Product_ID"], production["Plant"])]
        for component in components:
            grouped_components[(component["Component_Material_ID"], component["Component_Unit"])] += float(component["Component_Quantity"])
        for (material, unit), component_quantity in grouped_components.items():
            required = production["Remaining_Quantity"] / components[0]["Base_Quantity"] * component_quantity
            demands.append({**production, "Material_ID": material, "Quantity_Unit": unit, "Required_Quantity": float(required), "Material_Need_Date": production["Planned_Start_Date"]})
    demands.sort(key=lambda r: (r["Material_Need_Date"], r["Production_Order_ID"], r["Production_Order_Item"], r["Material_ID"]))

    grouped_inventory: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in scenario.sheets["Inventory"]:
        grouped_inventory[(row["Material_ID"], row["Plant"], row["Base_Unit"])].append(row)
    pools: dict[tuple[str, str, str], dict[str, float]] = {}
    for key, rows in grouped_inventory.items():
        unrestricted = sum(float(r["Quantity"]) for r in rows if r["Stock_Type"] == "UNRESTRICTED")
        safety = float(rows[0]["Safety_Stock"])
        usable = max(0.0, unrestricted - safety)
        pools[key] = {"unrestricted": unrestricted, "safety": safety, "usable": usable, "remaining": usable}

    receipts: list[dict[str, Any]] = []
    for row in scenario.sheets["Incoming_PO"]:
        if row["PO_Status"] not in {"OPEN", "PARTIALLY_RECEIVED"} or row["Deletion_Flag"] or row["Completely_Delivered_Flag"] or row["Open_Quantity"] <= 0:
            continue
        receipts.append({**row, "remaining": float(row["Open_Quantity"])})
    receipts.sort(key=lambda r: (r["Expected_Receipt_Date"], r["PO_ID"], r["PO_Item"], r["Schedule_Line"]))

    output: list[dict[str, Any]] = []
    for sequence, demand in enumerate(demands, 1):
        key = (demand["Material_ID"], demand["Plant"], demand["Quantity_Unit"])
        pool = pools.setdefault(key, {"unrestricted": 0.0, "safety": 0.0, "usable": 0.0, "remaining": 0.0})
        inventory_before = pool["remaining"]
        inventory_allocated = min(demand["Required_Quantity"], inventory_before)
        pool["remaining"] -= inventory_allocated
        need = demand["Required_Quantity"] - inventory_allocated
        matching = [r for r in receipts if (r["Material_ID"], r["Plant"], r["Quantity_Unit"]) == key]
        overdue = [r for r in matching if r["Expected_Receipt_Date"] < ANALYSIS_DATE]
        eligible = [r for r in matching if ANALYSIS_DATE <= r["Expected_Receipt_Date"] <= demand["Material_Need_Date"] and r["remaining"] > 0]
        eligible_before = sum(r["remaining"] for r in eligible)
        po_allocated = 0.0; used: list[str] = []; allocated_dates: list[date] = []
        for receipt in eligible:
            quantity = min(need, receipt["remaining"])
            if quantity <= 0: continue
            receipt["remaining"] -= quantity; need -= quantity; po_allocated += quantity
            allocated_dates.append(receipt["Expected_Receipt_Date"])
            used.append(f"{receipt['PO_ID']}/{receipt['PO_Item']}/{receipt['Schedule_Line']}:{quantity:g}")
        shortage = max(0.0, need)
        late = sum(r["remaining"] for r in matching if r["Expected_Receipt_Date"] >= ANALYSIS_DATE and r["Expected_Receipt_Date"] > demand["Material_Need_Date"])
        remaining_dates = [r["Expected_Receipt_Date"] for r in matching if r["Expected_Receipt_Date"] >= ANALYSIS_DATE and r["remaining"] > 0]
        latest = max(allocated_dates, default=None)
        priority, rule = _priority(shortage, demand["Material_Need_Date"], latest)
        output.append({
            "Sales_Order_ID": demand.get("Source_Sales_Order_ID"), "Sales_Order_Item": demand.get("Source_Sales_Order_Item"),
            "Production_Order_ID": demand["Production_Order_ID"], "Production_Order_Item": demand["Production_Order_Item"],
            "Material_ID": demand["Material_ID"], "Plant": demand["Plant"], "Quantity_Unit": demand["Quantity_Unit"],
            "Required_Quantity": demand["Required_Quantity"], "Unrestricted_Inventory": pool["unrestricted"], "Safety_Stock": pool["safety"],
            "Usable_Inventory": pool["usable"], "Inventory_Available_Before_Allocation": inventory_before,
            "Eligible_Incoming_Quantity": eligible_before, "Late_Incoming_Quantity": late,
            "Overdue_Incoming_Quantity": sum(r["remaining"] for r in overdue),
            "Overdue_PO_Lines": ", ".join(f"{r['PO_ID']}/{r['PO_Item']}/{r['Schedule_Line']}:{r['remaining']:g}" for r in overdue),
            "Inventory_Allocated": inventory_allocated, "Incoming_PO_Allocated": po_allocated,
            "Shortage_Quantity": shortage, "Remaining_Inventory_After_Allocation": pool["remaining"],
            "Next_Receipt_Date": min(remaining_dates).isoformat() if remaining_dates else None,
            "Latest_Required_Receipt_Date": latest.isoformat() if latest else None,
            "Allocated_PO_Lines": ", ".join(used), "Allocation_Sequence": sequence,
            "Priority": priority, "Priority_Rule_ID": rule,
        })
    return output


def build_aggregate_expected(scenario: Scenario) -> dict[str, Any]:
    """Roll up independent full rows into the required fixed aggregate contract."""

    rows = build_full_expected(scenario)
    priorities = Counter(row["Priority_Rule_ID"] for row in rows)
    plants: dict[str, dict[str, float]] = defaultdict(lambda: {"required": 0.0, "inventory_allocated": 0.0, "incoming_po_allocated": 0.0, "shortage": 0.0})
    for row in rows:
        plant = plants[row["Plant"]]
        plant["required"] += row["Required_Quantity"]; plant["inventory_allocated"] += row["Inventory_Allocated"]
        plant["incoming_po_allocated"] += row["Incoming_PO_Allocated"]; plant["shortage"] += row["Shortage_Quantity"]
    return {
        "input_row_count_per_sheet": scenario.row_counts, "output_result_row_count": len(rows),
        "total_required_quantity": sum(r["Required_Quantity"] for r in rows),
        "total_inventory_allocated": sum(r["Inventory_Allocated"] for r in rows),
        "total_incoming_po_allocated": sum(r["Incoming_PO_Allocated"] for r in rows),
        "total_shortage_quantity": sum(r["Shortage_Quantity"] for r in rows),
        "shortage_row_count": sum(r["Shortage_Quantity"] > 0 for r in rows),
        "non_shortage_row_count": sum(r["Shortage_Quantity"] == 0 for r in rows),
        "priority_distribution": {rule: priorities.get(rule, 0) for rule in ("P1", "P2", "P3A", "P3B", "P4")},
        "warning_count": 0, "warning_codes": [], "ignored_count": 0, "ignored_reasons": [], "data_error_count": 0,
        "by_plant": dict(plants),
    }
