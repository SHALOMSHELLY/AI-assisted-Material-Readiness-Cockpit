"""Deterministic supply-chain exception detection.

The LLM never participates in this module.  Every exception is derived from
validated workbook rows or the existing shortage engine output.
"""

from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
from typing import Any

import pandas as pd

from src.shortage_engine import AnalysisResult


ACTIVE_ORDER_STATUSES = {"OPEN", "CREATED", "RELEASED", "PARTIALLY_CONFIRMED"}
ACTIVE_PRODUCTION_STATUSES = {"CREATED", "RELEASED", "PARTIALLY_CONFIRMED"}
ACTIVE_PO_STATUSES = {"OPEN", "PARTIALLY_RECEIVED"}
PRIORITY_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
SUGGESTED_FUNCTION_BY_EXCEPTION = {
    "MATERIAL_SHORTAGE": "Procurement",
    "LATE_INCOMING_SUPPLY": "Procurement",
    "OVERDUE_INCOMING_SUPPLY": "Procurement",
    "UNSCHEDULED_ORDER": "Production Planning",
    "PRODUCTION_BACKLOG": "Production Planning",
    "PLANNED_COMPLETION_AFTER_REQUESTED_DELIVERY": "Production Planning",
    "ZERO_SCHEDULE_BUFFER": "Production Planning",
    "OVERDUE_INCOMING_PO": "Procurement",
}
ACTION_SEQUENCE_BY_EXCEPTION = {
    "PRODUCTION_BACKLOG": 10,
    "MATERIAL_SHORTAGE": 20,
    "PLANNED_COMPLETION_AFTER_REQUESTED_DELIVERY": 30,
    "UNSCHEDULED_ORDER": 40,
    "ZERO_SCHEDULE_BUFFER": 45,
    "LATE_INCOMING_SUPPLY": 50,
    "OVERDUE_INCOMING_SUPPLY": 60,
    "OVERDUE_INCOMING_PO": 80,
}


def _text(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    value = str(value).strip()
    return value or None


def _stable_id(exception_type: str, analysis_date: date, identity: dict[str, Any]) -> str:
    payload = json.dumps(identity, sort_keys=True, default=str, separators=(",", ":"))
    digest = sha256(f"{exception_type}|{analysis_date.isoformat()}|{payload}".encode()).hexdigest()[:14].upper()
    return f"EX-{exception_type[:4]}-{digest}"


def _priority(days: int, *, shortage_priority: str | None = None) -> tuple[str, str]:
    if shortage_priority:
        return shortage_priority, "SHORTAGE_PRIORITY"
    if days <= 2:
        return "Critical", "EX-P1"
    if days <= 7:
        return "High", "EX-P2"
    if days <= 14:
        return "Medium", "EX-P3"
    return "Low", "EX-P4"


def build_exception_register(
    sheets: dict[str, pd.DataFrame], result: AnalysisResult, analysis_date: date
) -> pd.DataFrame:
    """Return one stable, de-duplicated row per deterministic exception."""

    rows: list[dict[str, Any]] = []

    def add(exception_type: str, *, identity: dict[str, Any], facts: dict[str, Any],
            priority: str, rule_id: str, role: str,
            impact_class: str = "AT_RISK", direct_order_impact: bool = True,
            action_urgency: str | None = None) -> None:
        row = {
            "Exception_ID": _stable_id(exception_type, analysis_date, identity),
            "Exception_Type": exception_type,
            "Analysis_Date": analysis_date,
            "Sales_Order_ID": None,
            "Sales_Order_Item": None,
            "Product_ID": None,
            "Production_Order_ID": None,
            "Production_Order_Item": None,
            "Material_ID": None,
            "Plant": None,
            "Material_Need_Date": None,
            "Required_Quantity": 0.0,
            "Shortage_Quantity": 0.0,
            "Quantity_Unit": None,
            "Priority": priority,
            "Priority_Rule_ID": rule_id,
            "Impact_Class": impact_class,
            "Direct_Order_Impact": direct_order_impact,
            "Action_Urgency": action_urgency or priority,
            "Action_Sequence": ACTION_SEQUENCE_BY_EXCEPTION.get(exception_type, 99),
            # Backwards-compatible internal field. User-facing labels and new
            # exports call this a suggested function, never an assignment.
            "Responsible_Role": role,
            "Workflow_Status": "NEW",
            "Detected_Date": analysis_date,
            "Supporting_Facts": json.dumps(facts, default=str, sort_keys=True),
            "Source_Row_Identity": json.dumps(identity, default=str, sort_keys=True),
        }
        row.update({key: value for key, value in facts.items() if key in row})
        rows.append(row)

    shortage = result.shortage_results
    if not shortage.empty:
        for record in shortage.to_dict("records"):
            base = {
                "Sales_Order_ID": _text(record.get("Source_Sales_Order_ID")),
                "Sales_Order_Item": _text(record.get("Source_Sales_Order_Item")),
                "Product_ID": _text(record.get("Product_ID")),
                "Production_Order_ID": _text(record.get("Production_Order_ID")),
                "Production_Order_Item": _text(record.get("Production_Order_Item")),
                "Material_ID": _text(record.get("Material_ID")),
                "Plant": _text(record.get("Plant")),
                "Material_Need_Date": record.get("Material_Need_Date"),
                "Required_Quantity": float(record.get("Required_Quantity", 0)),
                "Shortage_Quantity": float(record.get("Shortage_Quantity", 0)),
                "Quantity_Unit": _text(record.get("Quantity_Unit")),
                "Inventory_Allocated": float(record.get("Inventory_Allocated", 0)),
                "Incoming_PO_Allocated": float(record.get("Incoming_PO_Allocated", 0)),
                "Eligible_Incoming_Quantity": float(record.get("Eligible_Incoming_Quantity", 0)),
                "Unrestricted_Inventory": float(record.get("Unrestricted_Inventory", 0)),
                "Safety_Stock": float(record.get("Safety_Stock", 0)),
                "Usable_Inventory": float(record.get("Usable_Inventory", 0)),
                "Inventory_Available_Before_Allocation": float(record.get("Inventory_Available_Before_Allocation", 0)),
                "Overdue_Incoming_Quantity": float(record.get("Overdue_Incoming_Quantity", 0)),
                "Overdue_PO_Lines": _text(record.get("Overdue_PO_Lines")),
                "Supply_Relationship": "MATERIAL_PLANT_POOL",
                "Directly_Pegged_To_Order": False,
            }
            identity = {key: base[key] for key in ("Production_Order_ID", "Production_Order_Item", "Material_ID", "Plant")}
            if base["Shortage_Quantity"] > 0:
                add("MATERIAL_SHORTAGE", identity=identity, facts=base,
                    priority=str(record["Priority"]), rule_id=str(record["Priority_Rule_ID"]),
                    role=SUGGESTED_FUNCTION_BY_EXCEPTION["MATERIAL_SHORTAGE"], impact_class="BLOCKING")
            if float(record.get("Late_Incoming_Quantity", 0)) > 0:
                facts = {**base, "Late_Incoming_Quantity": float(record["Late_Incoming_Quantity"]),
                         "Next_Receipt_Date": record.get("Next_Receipt_Date")}
                covered = base["Shortage_Quantity"] <= 0
                if covered:
                    priority, rule_id = "Low", "EX-MONITOR-COVERED-SUPPLY"
                else:
                    priority, rule_id = str(record["Priority"]), str(record["Priority_Rule_ID"])
                add("LATE_INCOMING_SUPPLY", identity={**identity, "kind": "late"}, facts=facts,
                    priority=priority, rule_id=rule_id, role=SUGGESTED_FUNCTION_BY_EXCEPTION["LATE_INCOMING_SUPPLY"],
                    impact_class="MONITOR" if covered else "AT_RISK", direct_order_impact=not covered)
            if base["Overdue_Incoming_Quantity"] > 0:
                covered = base["Shortage_Quantity"] <= 0
                if covered:
                    priority, rule_id = "Low", "EX-MONITOR-COVERED-SUPPLY"
                else:
                    priority, rule_id = str(record["Priority"]), str(record["Priority_Rule_ID"])
                add(
                    "OVERDUE_INCOMING_SUPPLY",
                    identity={**identity, "kind": "overdue"},
                    facts=base,
                    priority=priority,
                    rule_id=rule_id,
                    role=SUGGESTED_FUNCTION_BY_EXCEPTION["OVERDUE_INCOMING_SUPPLY"],
                    impact_class="MONITOR" if covered else "AT_RISK",
                    direct_order_impact=not covered,
                )

    production = sheets["Production_Orders"]
    linked = {
        (_text(row.Source_Sales_Order_ID), _text(row.Source_Sales_Order_Item))
        for row in production.itertuples()
        if _text(row.Source_Sales_Order_ID)
        and (
            (str(row.Order_Status).upper() in ACTIVE_PRODUCTION_STATUSES and float(row.Remaining_Quantity) > 0)
            or float(row.Remaining_Quantity) <= 0
            or str(row.Order_Status).upper() in {"CONFIRMED", "COMPLETED", "CLOSED", "TECO"}
        )
    }
    for row in sheets["Orders"].itertuples():
        key = (_text(row.Sales_Order_ID), _text(row.Sales_Order_Item))
        if str(row.Order_Status).upper() in ACTIVE_ORDER_STATUSES and float(row.Requested_Quantity) > 0 and key not in linked:
            days = (pd.Timestamp(row.Requested_Delivery_Date).date() - analysis_date).days
            priority, rule_id = _priority(days)
            facts = {"Sales_Order_ID": key[0], "Sales_Order_Item": key[1], "Product_ID": _text(row.Product_ID),
                     "Plant": _text(row.Plant), "Required_Quantity": float(row.Requested_Quantity),
                     "Quantity_Unit": _text(row.Quantity_Unit), "Material_Need_Date": pd.Timestamp(row.Requested_Delivery_Date).date()}
            add("UNSCHEDULED_ORDER", identity={"sales_order": key, "plant": row.Plant}, facts=facts,
                priority=priority, rule_id=rule_id, role=SUGGESTED_FUNCTION_BY_EXCEPTION["UNSCHEDULED_ORDER"],
                impact_class="AT_RISK")

    for row in production.itertuples():
        end_date = pd.Timestamp(row.Planned_End_Date).date()
        if str(row.Order_Status).upper() in ACTIVE_PRODUCTION_STATUSES and float(row.Remaining_Quantity) > 0 and end_date < analysis_date:
            days = (end_date - analysis_date).days
            priority, rule_id = _priority(days)
            facts = {"Sales_Order_ID": _text(row.Source_Sales_Order_ID), "Sales_Order_Item": _text(row.Source_Sales_Order_Item),
                     "Product_ID": _text(row.Product_ID), "Production_Order_ID": _text(row.Production_Order_ID),
                     "Production_Order_Item": _text(row.Production_Order_Item), "Plant": _text(row.Plant),
                     "Required_Quantity": float(row.Remaining_Quantity), "Quantity_Unit": _text(row.Quantity_Unit),
                     "Material_Need_Date": end_date, "Production_Order_Status": _text(row.Order_Status),
                     "Planned_Start_Date": pd.Timestamp(row.Planned_Start_Date).date(),
                     "Planned_End_Date": end_date, "Total_Quantity": float(row.Total_Quantity),
                     "Confirmed_Yield_Quantity": float(row.Confirmed_Yield_Quantity),
                     "Remaining_Quantity": float(row.Remaining_Quantity)}
            add("PRODUCTION_BACKLOG", identity={"production_order": row.Production_Order_ID, "item": row.Production_Order_Item},
                facts=facts, priority=priority, rule_id=rule_id, role=SUGGESTED_FUNCTION_BY_EXCEPTION["PRODUCTION_BACKLOG"],
                impact_class="BLOCKING")

    order_due_dates = {
        (_text(row.Sales_Order_ID), _text(row.Sales_Order_Item)): pd.Timestamp(row.Requested_Delivery_Date).date()
        for row in sheets["Orders"].itertuples()
    }
    for row in production.itertuples():
        order_key = (_text(row.Source_Sales_Order_ID), _text(row.Source_Sales_Order_Item))
        if order_key not in order_due_dates:
            continue
        if str(row.Order_Status).upper() not in ACTIVE_PRODUCTION_STATUSES or float(row.Remaining_Quantity) <= 0:
            continue
        requested_date = order_due_dates[order_key]
        planned_end = pd.Timestamp(row.Planned_End_Date).date()
        days_after = (planned_end - requested_date).days
        if days_after < 0:
            continue
        exception_type = (
            "PLANNED_COMPLETION_AFTER_REQUESTED_DELIVERY" if days_after > 0 else "ZERO_SCHEDULE_BUFFER"
        )
        if days_after > 0:
            days_to_delivery = (requested_date - analysis_date).days
            priority, rule_id = _priority(days_to_delivery)
            impact_class, direct = "AT_RISK", True
        else:
            priority, rule_id = "Low", "EX-MONITOR-ZERO-BUFFER"
            impact_class, direct = "MONITOR", False
        facts = {
            "Sales_Order_ID": order_key[0], "Sales_Order_Item": order_key[1],
            "Product_ID": _text(row.Product_ID), "Production_Order_ID": _text(row.Production_Order_ID),
            "Production_Order_Item": _text(row.Production_Order_Item), "Plant": _text(row.Plant),
            "Required_Quantity": float(row.Remaining_Quantity), "Quantity_Unit": _text(row.Quantity_Unit),
            "Material_Need_Date": requested_date, "Requested_Delivery_Date": requested_date,
            "Planned_Start_Date": pd.Timestamp(row.Planned_Start_Date).date(),
            "Planned_End_Date": planned_end, "Days_After_Requested_Delivery": days_after,
            "Production_Order_Status": _text(row.Order_Status), "Remaining_Quantity": float(row.Remaining_Quantity),
        }
        add(
            exception_type,
            identity={"production_order": row.Production_Order_ID, "item": row.Production_Order_Item, "kind": exception_type},
            facts=facts,
            priority=priority,
            rule_id=rule_id,
            role=SUGGESTED_FUNCTION_BY_EXCEPTION[exception_type],
            impact_class=impact_class,
            direct_order_impact=direct,
        )

    for row in sheets["Incoming_PO"].itertuples():
        receipt = pd.Timestamp(row.Expected_Receipt_Date).date()
        open_qty = float(row.Open_Quantity)
        active = str(row.PO_Status).upper() in ACTIVE_PO_STATUSES and not bool(row.Deletion_Flag) and not bool(row.Completely_Delivered_Flag)
        if active and open_qty > 0 and receipt < analysis_date:
            priority, rule_id = _priority((receipt - analysis_date).days)
            facts = {"Material_ID": _text(row.Material_ID), "Plant": _text(row.Plant), "Material_Need_Date": receipt,
                     "Required_Quantity": open_qty, "Quantity_Unit": _text(row.Quantity_Unit),
                     "PO_ID": _text(row.PO_ID), "PO_Item": _text(row.PO_Item), "Schedule_Line": _text(row.Schedule_Line)}
            identity = {key: facts[key] for key in ("PO_ID", "PO_Item", "Schedule_Line", "Plant")}
            add("OVERDUE_INCOMING_PO", identity=identity, facts=facts, priority=priority,
                rule_id=rule_id, role=SUGGESTED_FUNCTION_BY_EXCEPTION["OVERDUE_INCOMING_PO"],
                impact_class="MONITOR", direct_order_impact=False)

    columns = [
        "Exception_ID", "Exception_Type", "Analysis_Date", "Sales_Order_ID", "Sales_Order_Item",
        "Product_ID", "Production_Order_ID", "Production_Order_Item", "Material_ID", "Plant",
        "Material_Need_Date", "Required_Quantity", "Shortage_Quantity", "Quantity_Unit", "Priority",
        "Priority_Rule_ID", "Responsible_Role", "Workflow_Status", "Detected_Date",
        "Impact_Class", "Direct_Order_Impact", "Action_Urgency", "Action_Sequence",
        "Supporting_Facts", "Source_Row_Identity",
    ]
    frame = pd.DataFrame(rows, columns=columns).drop_duplicates("Exception_ID")
    if frame.empty:
        return frame
    bom = sheets["BOM"]
    description_col = "Component_Material_Description" if "Component_Material_Description" in bom else "Component_Material_ID"
    category_col = "Material_Category" if "Material_Category" in bom else None
    bom_meta = bom.drop_duplicates(["Component_Material_ID", "Plant"]).copy()
    descriptions = {
        (str(row.Component_Material_ID), str(row.Plant)): str(getattr(row, description_col))
        for row in bom_meta.itertuples()
    }
    categories = ({
        (str(row.Component_Material_ID), str(row.Plant)): str(getattr(row, category_col))
        for row in bom_meta.itertuples()
    } if category_col else {})
    incoming = sheets["Incoming_PO"]
    supplier_col = "Supplier_Name" if "Supplier_Name" in incoming else "Supplier_ID"
    suppliers = incoming.groupby(["Material_ID", "Plant"])[supplier_col].agg(
        lambda values: ", ".join(sorted({str(value) for value in values if pd.notna(value)}))).to_dict()
    material_plant_keys = list(zip(frame["Material_ID"].astype(str), frame["Plant"].astype(str)))
    frame["Material_Description"] = [descriptions.get(key) for key in material_plant_keys]
    frame["Material_Description"] = frame["Material_Description"].fillna(frame["Material_ID"])
    frame["Material_Category"] = [categories.get(key) for key in material_plant_keys]
    frame["Material_Category"] = frame["Material_Category"].fillna("Not classified")
    frame["Supplier"] = [suppliers.get(key, "") for key in material_plant_keys]
    frame["_rank"] = frame["Priority"].map(PRIORITY_RANK).fillna(99)
    return frame.sort_values(["Action_Sequence", "_rank", "Material_Need_Date", "Exception_ID"], na_position="last").drop(columns="_rank").reset_index(drop=True)
