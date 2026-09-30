"""Order-scoped AI input and human-review presentation helpers."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from src.llm_prompt import build_structured_input


PRIORITY_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
EXCEPTION_TYPE_RANK = {
    "PRODUCTION_BACKLOG": 0,
    "MATERIAL_SHORTAGE": 1,
    "PLANNED_COMPLETION_AFTER_REQUESTED_DELIVERY": 2,
    "UNSCHEDULED_ORDER": 3,
    "ZERO_SCHEDULE_BUFFER": 4,
    "LATE_INCOMING_SUPPLY": 5,
    "OVERDUE_INCOMING_SUPPLY": 6,
    "OVERDUE_INCOMING_PO": 7,
}
MAX_MATERIAL_DETAILS = 15
MAX_PO_DETAILS = 10
# Eight fully reviewed exceptions leave enough room for concise findings,
# evidence-bound actions, and truncation disclosure within the 2,400-token
# output cap. The complete deterministic register remains available locally.
MAX_EXCEPTION_DETAILS = 8


def _material_signal_key(row: dict[str, Any] | pd.Series) -> tuple[str, str, str, str]:
    return tuple(
        str(row.get(column))
        for column in ("Production_Order_ID", "Production_Order_Item", "Material_ID", "Plant")
    )


def _validate_material_signal_coverage(scoped: pd.DataFrame, result_scope: pd.DataFrame) -> dict[str, int]:
    """Prove that every order-scoped material signal has an exception row."""
    actual = {
        (_material_signal_key(row), str(row.get("Exception_Type")))
        for row in scoped.to_dict("records")
    }
    expected: set[tuple[tuple[str, str, str, str], str]] = set()
    for row in result_scope.to_dict("records"):
        key = _material_signal_key(row)
        if float(row.get("Shortage_Quantity", 0) or 0) > 0:
            expected.add((key, "MATERIAL_SHORTAGE"))
        if float(row.get("Late_Incoming_Quantity", 0) or 0) > 0:
            expected.add((key, "LATE_INCOMING_SUPPLY"))
        if float(row.get("Overdue_Incoming_Quantity", 0) or 0) > 0:
            expected.add((key, "OVERDUE_INCOMING_SUPPLY"))
    missing = expected - actual
    if missing:
        raise ValueError(f"Order AI payload is incomplete; {len(missing)} material signals lack exceptions.")
    return {"expected_material_signal_count": len(expected), "covered_material_signal_count": len(expected)}


def _json_safe(value: Any) -> Any:
    if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
        return None
    if isinstance(value, (pd.Timestamp,)) or hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def payload_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    return {"payload_json_bytes": len(encoded), "estimated_input_tokens": (len(encoded) + 3) // 4,
            "token_count_method": "Estimated: UTF-8 JSON bytes / 4, rounded up"}


def inventory_coverage_message(exception: dict[str, Any]) -> str | None:
    """Return a deterministic display sentence for fully inventory-covered late supply."""
    if exception.get("Exception_Type") not in {"LATE_INCOMING_SUPPLY", "OVERDUE_INCOMING_SUPPLY"}:
        return None
    try:
        required = float(exception.get("Required_Quantity"))
        inventory = float(exception.get("Inventory_Allocated"))
        shortage = float(exception.get("Shortage_Quantity"))
    except (TypeError, ValueError):
        return None
    if required <= 0 or shortage != 0 or inventory < required:
        return None
    unit = str(exception.get("Quantity_Unit") or "").strip()
    suffix = f" {unit}" if unit else ""
    return (
        f"Inventory covers the full requirement: {inventory:g} of {required:g}{suffix} "
        "is allocated in the deterministic calculation."
    )


def _ordered_exceptions(scoped: pd.DataFrame) -> pd.DataFrame:
    """Return exceptions in deterministic business-priority order."""
    if scoped.empty:
        return scoped.copy()
    ranked = scoped.copy()
    impact = ranked["Impact_Class"] if "Impact_Class" in ranked else pd.Series("AT_RISK", index=ranked.index)
    ranked["_impact_rank"] = impact.map(
        {"BLOCKING": 0, "AT_RISK": 1, "MONITOR": 2}
    ).fillna(9)
    ranked["_priority_rank"] = ranked["Priority"].map(PRIORITY_RANK).fillna(99)
    ranked["_type_rank"] = ranked["Exception_Type"].map(EXCEPTION_TYPE_RANK).fillna(99)
    return ranked.sort_values(
        ["_impact_rank", "_type_rank", "_priority_rank", "Material_Need_Date", "Exception_ID"],
        na_position="last", kind="stable",
    ).drop(columns=["_impact_rank", "_priority_rank", "_type_rank"])


def _matching_result_row(result_scope: pd.DataFrame, exception: pd.Series | None) -> pd.Series | None:
    """Find the calculated material row that actually caused an exception."""
    if result_scope.empty:
        return None
    candidates = result_scope
    if exception is not None:
        for column in ("Production_Order_ID", "Production_Order_Item", "Material_ID", "Plant"):
            value = exception.get(column)
            if value is None or pd.isna(value) or str(value).strip() == "":
                continue
            candidates = candidates[candidates[column].astype(str) == str(value)]
            if candidates.empty:
                break
    if candidates.empty:
        return None
    ranked = candidates.assign(
        _priority_rank=candidates["Priority"].map(PRIORITY_RANK).fillna(99),
        _shortage=pd.to_numeric(candidates["Shortage_Quantity"], errors="coerce").fillna(0),
    )
    return ranked.sort_values(
        ["_priority_rank", "_shortage", "Material_Need_Date", "Material_ID"],
        ascending=[True, False, True, True], na_position="last", kind="stable",
    ).iloc[0]


def _exception_payload(row: dict[str, Any]) -> dict[str, Any]:
    """Expose each exception's deterministic facts as real JSON values."""
    fields = (
        "Exception_ID", "Exception_Type", "Analysis_Date", "Priority",
        "Sales_Order_ID", "Sales_Order_Item", "Product_ID", "Production_Order_ID",
        "Production_Order_Item", "Material_ID", "Plant", "Material_Need_Date",
        "Required_Quantity", "Shortage_Quantity", "Late_Incoming_Quantity",
        "Overdue_Incoming_Quantity", "Overdue_PO_Lines", "Next_Receipt_Date", "Quantity_Unit",
        "Priority_Rule_ID",
        "Unrestricted_Inventory", "Safety_Stock", "Usable_Inventory",
        "Inventory_Available_Before_Allocation", "Inventory_Allocated",
        "Incoming_PO_Allocated", "Eligible_Incoming_Quantity",
        "Production_Order_Status", "Planned_Start_Date", "Planned_End_Date",
        "Requested_Delivery_Date", "Days_After_Requested_Delivery",
        "Total_Quantity", "Confirmed_Yield_Quantity", "Remaining_Quantity",
        "Impact_Class", "Direct_Order_Impact", "Action_Urgency", "Action_Sequence",
        "Supply_Relationship", "Directly_Pegged_To_Order",
    )
    payload = {key: _json_safe(row.get(key)) for key in fields}
    # The response evidence schema uses Python_Priority. Keep the exception-
    # scoped alias explicit so the model does not have to infer it from Priority.
    payload["Python_Priority"] = _json_safe(row.get("Priority"))
    payload["Suggested_Responsible_Function"] = _json_safe(row.get("Responsible_Role"))
    raw_supporting = row.get("Supporting_Facts")
    try:
        supporting = json.loads(raw_supporting) if isinstance(raw_supporting, str) else raw_supporting
    except (TypeError, ValueError):
        supporting = None
    if isinstance(supporting, dict):
        supporting = {key: _json_safe(value) for key, value in supporting.items()}
        for key in payload:
            if payload.get(key) is None and key in supporting:
                payload[key] = supporting[key]
    payload["Supporting_Facts"] = supporting
    return payload


def build_order_ai_input(order_id: str, order_item: str, exceptions: pd.DataFrame,
                         shortage_results: pd.DataFrame, sheets: dict[str, pd.DataFrame] | None = None) -> dict[str, Any]:
    """Build a preview containing only facts for the selected sales-order item."""
    scoped = exceptions[
        (exceptions["Sales_Order_ID"].astype(str) == str(order_id))
        & (exceptions["Sales_Order_Item"].astype(str) == str(order_item))
    ]
    result_scope = shortage_results[
        (shortage_results["Source_Sales_Order_ID"].astype(str) == str(order_id))
        & (shortage_results["Source_Sales_Order_Item"].astype(str) == str(order_item))
    ] if not shortage_results.empty else shortage_results
    coverage = _validate_material_signal_coverage(scoped, result_scope)
    ordered_exceptions = _ordered_exceptions(scoped)
    facts = [_exception_payload(row) for row in ordered_exceptions.to_dict("records")]
    primary_exception = ordered_exceptions.iloc[0] if not ordered_exceptions.empty else None
    representative = None
    if not result_scope.empty:
        representative_row = _matching_result_row(result_scope, primary_exception)
        if representative_row is None and primary_exception is None:
            representative_row = _matching_result_row(result_scope, None)
        if representative_row is not None:
            representative = build_structured_input(representative_row)
            if primary_exception is not None:
                # Exception priority is authoritative for the order-level AI focus.
                # It may differ from the shortage row when inventory covers demand
                # but a late incoming delivery still requires planner attention.
                representative["Python_Priority"] = str(primary_exception["Priority"])
                representative["Priority_Rule_ID"] = str(primary_exception["Priority_Rule_ID"])
    if representative is None and primary_exception is not None:
        # Schedule-only exceptions (for example an order that has not yet been
        # assigned a production order) have no material-calculation row. Build
        # the top-level compatibility fields from the authoritative exception
        # instead of leaving priority and rule identifiers null.
        fallback_row = primary_exception.to_dict()
        fallback_row["Source_Sales_Order_ID"] = fallback_row.get("Sales_Order_ID")
        fallback_row["Source_Sales_Order_Item"] = fallback_row.get("Sales_Order_Item")
        representative = build_structured_input(fallback_row)
        representative["Python_Priority"] = str(primary_exception["Priority"])
        representative["Priority_Rule_ID"] = str(primary_exception["Priority_Rule_ID"])
    selected_order = {"Sales_Order_ID": str(order_id), "Sales_Order_Item": str(order_item)}
    if sheets is not None:
        orders = sheets["Orders"]
        match = orders[(orders["Sales_Order_ID"].astype(str) == str(order_id)) & (orders["Sales_Order_Item"].astype(str) == str(order_item))]
        if not match.empty:
            row = match.iloc[0]
            selected_order.update({
                key: _json_safe(row.get(key))
                for key in (
                    "Product_ID", "Product_Description", "Product_Family",
                    "Requested_Delivery_Date", "Plant",
                )
            })
    material_columns = [
        "Production_Order_ID", "Production_Order_Item", "Product_ID", "Material_ID", "Plant",
        "Material_Need_Date", "Required_Quantity", "Quantity_Unit", "Inventory_Allocated",
        "Incoming_PO_Allocated", "Shortage_Quantity", "Eligible_Incoming_Quantity",
        "Late_Incoming_Quantity", "Overdue_Incoming_Quantity", "Next_Receipt_Date",
        "Allocated_PO_Lines", "Priority", "Priority_Rule_ID",
    ]
    affected = result_scope[
        (pd.to_numeric(result_scope.get("Shortage_Quantity", 0), errors="coerce").fillna(0) > 0)
        | (pd.to_numeric(result_scope.get("Late_Incoming_Quantity", 0), errors="coerce").fillna(0) > 0)
        | (pd.to_numeric(result_scope.get("Overdue_Incoming_Quantity", 0), errors="coerce").fillna(0) > 0)
    ].copy() if not result_scope.empty else result_scope.copy()
    if not affected.empty:
        affected["_rank"] = affected["Priority"].map(PRIORITY_RANK).fillna(99)
        affected = affected.sort_values(
            ["_rank", "Shortage_Quantity", "Material_Need_Date", "Material_ID"],
            ascending=[True, False, True, True], kind="stable",
        )
    material_facts = [
        {key: _json_safe(row.get(key)) for key in material_columns}
        for row in affected.head(MAX_MATERIAL_DETAILS).to_dict("records")
    ]
    covered = result_scope.loc[~result_scope.index.isin(affected.index)] if not result_scope.empty else result_scope
    po_details: list[dict[str, Any]] = []
    if sheets is not None and not affected.empty:
        incoming = sheets["Incoming_PO"]
        affected_keys = {(str(row.Material_ID), str(row.Plant), str(row.Quantity_Unit)) for row in affected.itertuples()}
        need_dates = {
            key: min(pd.Timestamp(row.Material_Need_Date).date() for row in affected.itertuples()
                     if (str(row.Material_ID), str(row.Plant), str(row.Quantity_Unit)) == key)
            for key in affected_keys
        }
        supplier_col = "Supplier_Name" if "Supplier_Name" in incoming else "Supplier_ID"
        for po in incoming.itertuples(index=False):
            key = (str(po.Material_ID), str(po.Plant), str(po.Quantity_Unit))
            active = (str(po.PO_Status).strip().upper() in {"OPEN", "PARTIALLY_RECEIVED"}
                      and not bool(po.Deletion_Flag) and not bool(po.Completely_Delivered_Flag))
            if key not in affected_keys or not active or float(po.Open_Quantity) <= 0:
                continue
            receipt_date = pd.Timestamp(po.Expected_Receipt_Date).date()
            analysis = pd.Timestamp(representative["Analysis_Date"]).date() if representative else receipt_date
            status = ("Overdue" if receipt_date < analysis
                      else "Late" if receipt_date > need_dates[key] else "Eligible")
            po_details.append({
                "PO_ID": str(po.PO_ID), "PO_Item": str(po.PO_Item), "Schedule_Line": str(po.Schedule_Line),
                "Material_ID": str(po.Material_ID), "Plant": str(po.Plant), "Quantity_Unit": str(po.Quantity_Unit),
                "Supplier": _json_safe(getattr(po, supplier_col)), "Expected_Receipt_Date": receipt_date.isoformat(),
                "Open_Quantity": float(po.Open_Quantity), "status": status,
                "Supply_Relationship": "MATERIAL_PLANT_POOL", "Directly_Pegged_To_Order": False,
            })
        po_details.sort(key=lambda row: (row["Expected_Receipt_Date"], row["PO_ID"], row["PO_Item"], row["Schedule_Line"]))

    payload = dict(representative or {})
    has_material_shortage = bool(
        not result_scope.empty
        and (pd.to_numeric(result_scope["Shortage_Quantity"], errors="coerce").fillna(0) > 0).any()
    )
    has_late_or_overdue_supply = bool(
        not result_scope.empty
        and (
            (pd.to_numeric(result_scope["Late_Incoming_Quantity"], errors="coerce").fillna(0) > 0)
            | (pd.to_numeric(result_scope["Overdue_Incoming_Quantity"], errors="coerce").fillna(0) > 0)
        ).any()
    )
    primary_fact = facts[0] if facts else None
    related_po_materials = {row["Material_ID"] for row in po_details}
    required_missing_information: set[str] = set()
    for fact in facts:
        exception_type = fact.get("Exception_Type")
        material_id = fact.get("Material_ID")
        if exception_type in {"LATE_INCOMING_SUPPLY", "OVERDUE_INCOMING_SUPPLY"}:
            if material_id in related_po_materials:
                required_missing_information.add("SUPPLIER_CONFIRMATION")
            else:
                required_missing_information.update({"SOURCING_OR_PURCHASE_ORDER_STATUS", "SUPPLY_LEAD_TIME"})
            required_missing_information.add("CROSS_ORDER_SUPPLY_DEPENDENCIES")
        elif exception_type == "MATERIAL_SHORTAGE":
            if material_id in related_po_materials:
                required_missing_information.add("SUPPLIER_CONFIRMATION")
            else:
                required_missing_information.update({"SOURCING_OR_PURCHASE_ORDER_STATUS", "SUPPLY_LEAD_TIME"})
        elif exception_type in {
            "PRODUCTION_BACKLOG", "UNSCHEDULED_ORDER",
            "PLANNED_COMPLETION_AFTER_REQUESTED_DELIVERY", "ZERO_SCHEDULE_BUFFER",
        }:
            required_missing_information.add("PRODUCTION_SCHEDULE_CONSTRAINTS")
    payload.update({
        "Selected_Order": selected_order,
        "Primary_Exception": primary_fact,
        "Primary_Exception_Type": primary_fact["Exception_Type"] if primary_fact else None,
        "Verified_Exceptions": facts[:MAX_EXCEPTION_DETAILS],
        "Order_Exception_Count": int(len(facts)),
        "Order_Has_Material_Shortage": has_material_shortage,
        "Order_Has_Late_Or_Overdue_Supply": has_late_or_overdue_supply,
        "Affected_Material_Details": material_facts,
        "Covered_Material_Summary": {"covered_material_count": int(len(covered))},
        "Related_PO_Details": po_details[:MAX_PO_DETAILS],
        "Required_Missing_Information_Codes": sorted(required_missing_information),
        "Payload_Completeness": coverage,
        "payload_truncated": (
            len(facts) > MAX_EXCEPTION_DETAILS
            or len(affected) > MAX_MATERIAL_DETAILS
            or len(po_details) > MAX_PO_DETAILS
        ),
        "additional_exception_count": max(0, len(facts) - MAX_EXCEPTION_DETAILS),
        "additional_affected_material_count": max(0, len(affected) - MAX_MATERIAL_DETAILS),
        "additional_po_line_count": max(0, len(po_details) - MAX_PO_DETAILS),
        "human_review_required": True, "requires_human_approval": True, "execution_status": "NOT_EXECUTED",
    })
    payload["Fact_Package_Metadata"] = {
        "deterministic_facts": [
            "Selected_Order", "Primary_Exception", "Verified_Exceptions",
            "Order_Has_Material_Shortage", "Order_Has_Late_Or_Overdue_Supply",
            "Affected_Material_Details", "Covered_Material_Summary", "Related_PO_Details",
        ],
        "derived_relationships": "PO relationships are material-plant-pool relationships inferred through sales order, production order, BOM component, material, plant, and unit. They are not direct order commitments or pegging.",
        "missing_information": sorted(required_missing_information),
        "excluded_data": ["raw_workbook", "unrelated_orders", "secrets", "user_identity"],
        "truncation_information": {
            "payload_truncated": payload["payload_truncated"],
            "additional_exception_count": payload["additional_exception_count"],
            "additional_affected_material_count": payload["additional_affected_material_count"],
            "additional_po_line_count": payload["additional_po_line_count"],
        },
    }
    metrics = payload_metrics(payload)
    return {"analysis_date": representative.get("Analysis_Date") if representative else None,
            "selected_order": selected_order, "verified_exceptions": facts,
            "affected_material_facts": material_facts, "representative_shortage_fact": representative,
            "related_po_details": po_details[:MAX_PO_DETAILS], "llm_payload": payload,
            **metrics, "human_review_required": True, "execution_status": "NOT_EXECUTED"}
