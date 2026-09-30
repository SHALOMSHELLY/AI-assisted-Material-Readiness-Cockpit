"""Deterministic, presentation-ready views for the material readiness cockpit.

This module never changes the planning engine.  It only joins, aggregates and
filters already validated source rows and Python-calculated results.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from src.exception_engine import ACTIVE_ORDER_STATUSES, ACTIVE_PO_STATUSES, ACTIVE_PRODUCTION_STATUSES


BUSINESS_EXCEPTION_LABELS = {
    "MATERIAL_SHORTAGE": "Material Shortage",
    "LATE_INCOMING_SUPPLY": "Incoming Supply Arrives Too Late",
    "OVERDUE_INCOMING_SUPPLY": "Incoming Supply Is Overdue",
    "UNSCHEDULED_ORDER": "Pending Scheduling",
    "PRODUCTION_BACKLOG": "Production Backlog",
    "PLANNED_COMPLETION_AFTER_REQUESTED_DELIVERY": "Planned Completion After Requested Delivery",
    "ZERO_SCHEDULE_BUFFER": "Zero Schedule Buffer",
    "OVERDUE_INCOMING_PO": "Overdue Supplier PO",
}
PRIORITY_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
def business_exception_label(value: Any) -> str:
    return BUSINESS_EXCEPTION_LABELS.get(str(value), str(value).replace("_", " ").title())


def ai_candidate_exceptions(filtered_exceptions: pd.DataFrame, quick_filter: str,
                            sheets: dict[str, pd.DataFrame], shortage: pd.DataFrame,
                            analysis_date: date) -> pd.DataFrame:
    """Return exception rows whose orders are eligible for the AI selector.

    This function only narrows the candidate *orders*.  The caller must use the
    complete exception register when building an AI payload for the selected
    order, so a UI filter can never hide one of that order's verified exceptions.
    """
    candidates = filtered_exceptions.copy()
    if candidates.empty or quick_filter == "All":
        return candidates

    keys: set[tuple[str, str]] = set()
    if quick_filter in {"Shortage — Switches", "Shortage — Controllers"}:
        category = "Switch" if quick_filter.endswith("Switches") else "Controller"
        bom = sheets["BOM"]
        material_ids = set(
            bom.loc[bom.Material_Category.astype(str) == category, "Component_Material_ID"].astype(str)
        )
        matching = shortage[
            (pd.to_numeric(shortage.Shortage_Quantity, errors="coerce").fillna(0) > 0)
            & shortage.Material_ID.astype(str).isin(material_ids)
        ]
        keys = set(zip(
            matching.Source_Sales_Order_ID.astype(str),
            matching.Source_Sales_Order_Item.astype(str),
        ))
    elif quick_filter == "Pending Scheduling":
        pending = pending_scheduling(sheets, analysis_date, filtered_exceptions)
        keys = set(zip(
            pending.get("Sales_Order_ID", pd.Series(dtype=str)).astype(str),
            pending.get("Sales_Order_Item", pd.Series(dtype=str)).astype(str),
        ))
    else:
        return candidates

    order_keys = pd.Series(
        list(zip(candidates.Sales_Order_ID.astype(str), candidates.Sales_Order_Item.astype(str))),
        index=candidates.index,
    )
    return candidates[order_keys.isin(keys)].copy()


def _join(values) -> str:
    return ", ".join(sorted({str(v) for v in values if pd.notna(v) and str(v).strip()}))


def _highest(values) -> str:
    return min((str(v) for v in values if pd.notna(v)), key=lambda v: PRIORITY_RANK.get(v, 99), default="Low")


def _allocated_po_keys(needs: pd.DataFrame) -> set[tuple[str, str, str]]:
    """Parse exact PO schedule-line keys from deterministic allocation details."""
    keys: set[tuple[str, str, str]] = set()
    if needs.empty or "Allocated_PO_Lines" not in needs:
        return keys
    for value in needs["Allocated_PO_Lines"].dropna().astype(str):
        for allocation in value.split(","):
            reference = allocation.strip().rsplit(":", 1)[0]
            parts = reference.rsplit("/", 2)
            if len(parts) == 3 and all(parts):
                keys.add(tuple(parts))
    return keys


def pending_scheduling(sheets: dict[str, pd.DataFrame], analysis_date: date, exceptions: pd.DataFrame) -> pd.DataFrame:
    """Apply the existing deterministic definition without relying on exception filtering."""
    orders, production = sheets["Orders"].copy(), sheets["Production_Orders"]
    active_links = {
        (str(r.Source_Sales_Order_ID), str(r.Source_Sales_Order_Item))
        for r in production.itertuples()
        if str(r.Order_Status).upper() in ACTIVE_PRODUCTION_STATUSES
        and float(r.Remaining_Quantity) > 0 and pd.notna(r.Source_Sales_Order_ID)
    }
    completed_links = {
        (str(r.Source_Sales_Order_ID), str(r.Source_Sales_Order_Item))
        for r in production.itertuples()
        if pd.notna(r.Source_Sales_Order_ID)
        and (
            float(r.Remaining_Quantity) <= 0
            or str(r.Order_Status).upper() in {"CONFIRMED", "COMPLETED", "CLOSED", "TECO"}
        )
    }
    rows = []
    for order in orders.itertuples():
        key = (str(order.Sales_Order_ID), str(order.Sales_Order_Item))
        if (str(order.Order_Status).upper() not in ACTIVE_ORDER_STATUSES
                or float(order.Requested_Quantity) <= 0 or key in active_links or key in completed_links):
            continue
        due = pd.Timestamp(order.Requested_Delivery_Date).date()
        scoped = exceptions[(exceptions.Sales_Order_ID.astype(str) == key[0]) &
                            (exceptions.Sales_Order_Item.astype(str) == key[1])]
        rows.append({
            "Sales_Order_ID": key[0], "Sales_Order_Item": key[1], "Product_ID": str(order.Product_ID),
            "Requested_Quantity": float(order.Requested_Quantity), "Quantity_Unit": str(order.Quantity_Unit),
            "Requested_Delivery_Date": due, "Plant": str(order.Plant),
            "Days_Until_Delivery": (due - analysis_date).days,
            "Priority": _highest(scoped.Priority) if not scoped.empty else "Low",
            "Scheduling_Status": "Pending Scheduling",
            "Reason": "No valid active linked production order.",
        })
    return pd.DataFrame(rows)


def build_orders_view(sheets: dict[str, pd.DataFrame], shortage: pd.DataFrame,
                      exceptions: pd.DataFrame, analysis_date: date) -> pd.DataFrame:
    """Return every sales order, including orders with no exception."""
    orders = sheets["Orders"].copy()
    production = sheets["Production_Orders"]
    pending = pending_scheduling(sheets, analysis_date, exceptions)
    pending_keys = set(zip(pending.get("Sales_Order_ID", []), pending.get("Sales_Order_Item", [])))
    active_keys = {
        (str(r.Source_Sales_Order_ID), str(r.Source_Sales_Order_Item))
        for r in production.itertuples()
        if pd.notna(r.Source_Sales_Order_ID)
        and str(r.Order_Status).upper() in ACTIVE_PRODUCTION_STATUSES
        and float(r.Remaining_Quantity) > 0
    }
    completed_keys = {
        (str(r.Source_Sales_Order_ID), str(r.Source_Sales_Order_Item))
        for r in production.itertuples()
        if pd.notna(r.Source_Sales_Order_ID)
        and (
            float(r.Remaining_Quantity) <= 0
            or str(r.Order_Status).upper() in {"CONFIRMED", "COMPLETED", "CLOSED", "TECO"}
        )
    }
    rows = []
    for order in orders.itertuples():
        oid, item = str(order.Sales_Order_ID), str(order.Sales_Order_Item)
        req = shortage[(shortage.Source_Sales_Order_ID.astype(str) == oid) &
                       (shortage.Source_Sales_Order_Item.astype(str) == item)] if not shortage.empty else shortage
        exc = exceptions[(exceptions.Sales_Order_ID.astype(str) == oid) &
                         (exceptions.Sales_Order_Item.astype(str) == item)]
        linked = production[(production.Source_Sales_Order_ID.astype(str) == oid) &
                            (production.Source_Sales_Order_Item.astype(str) == item)]
        types = [business_exception_label(v) for v in exc.Exception_Type] if not exc.empty else []
        affected = req[
            (pd.to_numeric(req["Shortage_Quantity"], errors="coerce").fillna(0) > 0)
            | (pd.to_numeric(req["Late_Incoming_Quantity"], errors="coerce").fillna(0) > 0)
            | (pd.to_numeric(req["Overdue_Incoming_Quantity"], errors="coerce").fillna(0) > 0)
        ] if not req.empty else req
        scheduling_status = (
            "Pending Scheduling" if (oid, item) in pending_keys
            else "Scheduled" if (oid, item) in active_keys
            else "Production Complete / Awaiting Delivery" if (oid, item) in completed_keys
            else "Scheduled"
        )
        rows.append({
            "Sales_Order_ID": oid, "Sales_Order_Item": item, "Product_ID": str(order.Product_ID),
            "Product_Description": getattr(order, "Product_Description", order.Product_ID),
            "Requested_Quantity": float(order.Requested_Quantity), "Quantity_Unit": str(order.Quantity_Unit),
            "Requested_Delivery_Date": pd.Timestamp(order.Requested_Delivery_Date).date(), "Plant": str(order.Plant),
            "Scheduling_Status": scheduling_status,
            "Related_Production_Orders": _join(linked.Production_Order_ID),
            "Highest_Priority": _highest(exc.Priority) if not exc.empty else (_highest(req.Priority) if not req.empty else "Low"),
            "Affected_Materials": int(affected.Material_ID.nunique()) if not affected.empty else 0,
            "Total_Shortage": float(pd.to_numeric(req.Shortage_Quantity).sum()) if not req.empty else 0.0,
            "Exception_Summary": ", ".join(sorted(set(types))) or "No exception detected",
        })
    return pd.DataFrame(rows)


def build_materials_view(sheets: dict[str, pd.DataFrame], shortage: pd.DataFrame) -> pd.DataFrame:
    if shortage.empty:
        return pd.DataFrame()
    bom = sheets["BOM"]
    desc_col = "Component_Material_Description" if "Component_Material_Description" in bom else "Component_Material_ID"
    meta = bom.drop_duplicates(["Component_Material_ID", "Plant"]).copy()
    grouped = shortage.groupby(["Material_ID", "Plant", "Quantity_Unit"], dropna=False).agg(
        Total_Required=("Required_Quantity", "sum"), Usable_Inventory=("Usable_Inventory", "max"),
        # Eligible_Incoming_Quantity is a rolling pre-allocation balance and must
        # never be summed across demand rows.  Keep its maximum as a conservative
        # backwards-compatible diagnostic, while the UI uses actual allocation.
        Eligible_Incoming_Supply=("Eligible_Incoming_Quantity", "max"),
        # Actual allocation is additive and is therefore the reliable
        # material-level incoming-supply measure.
        Incoming_PO_Allocated=("Incoming_PO_Allocated", "sum"), Total_Shortage=("Shortage_Quantity", "sum"),
        Late_Incoming_Supply=("Late_Incoming_Quantity", "max"),
        Overdue_Incoming_Supply=("Overdue_Incoming_Quantity", "max"),
        Earliest_Need_Date=("Material_Need_Date", "min"), Highest_Priority=("Priority", _highest),
        Affected_Sales_Orders=("Source_Sales_Order_ID", lambda x: len(set(x.dropna().astype(str)))),
        Affected_Production_Orders=("Production_Order_ID", lambda x: len(set(x.dropna().astype(str)))),
    ).reset_index()
    descriptions = {
        (str(row.Component_Material_ID), str(row.Plant)): (
            str(row.Component_Material_ID) if desc_col == "Component_Material_ID" else str(getattr(row, desc_col))
        )
        for row in meta.itertuples()
    }
    categories = ({
        (str(row.Component_Material_ID), str(row.Plant)): str(row.Material_Category)
        for row in meta.itertuples()
    } if "Material_Category" in meta else {})
    keys = list(zip(grouped.Material_ID.astype(str), grouped.Plant.astype(str)))
    grouped["Description"] = [descriptions.get(key, key[0]) for key in keys]
    grouped["Category"] = [categories.get(key, "Not classified") for key in keys]
    return grouped[["Material_ID", "Description", "Category", "Plant", "Quantity_Unit", "Total_Required",
                    "Usable_Inventory", "Eligible_Incoming_Supply", "Incoming_PO_Allocated", "Total_Shortage",
                    "Late_Incoming_Supply", "Overdue_Incoming_Supply", "Earliest_Need_Date",
                    "Highest_Priority", "Affected_Sales_Orders", "Affected_Production_Orders"]]


def po_schedule_lines(material_id: str, plant: str, sheets: dict[str, pd.DataFrame],
                      shortage: pd.DataFrame, analysis_date: date) -> pd.DataFrame:
    """Return source PO schedule lines with explicit eligibility and derived relationship wording."""
    incoming = sheets["Incoming_PO"]
    scoped = incoming[(incoming.Material_ID.astype(str) == str(material_id)) &
                      (incoming.Plant.astype(str) == str(plant))].copy()
    needs = shortage[(shortage.Material_ID.astype(str) == str(material_id)) &
                     (shortage.Plant.astype(str) == str(plant))] if not shortage.empty else shortage
    need_date = pd.to_datetime(needs.Material_Need_Date).min().date() if not needs.empty else None
    allocated_keys = _allocated_po_keys(needs)
    related_orders = _join(needs.Source_Sales_Order_ID) if not needs.empty else ""
    rows = []
    supplier_col = "Supplier_Name" if "Supplier_Name" in scoped else "Supplier_ID"
    for po in scoped.itertuples(index=False):
        receipt = pd.Timestamp(po.Expected_Receipt_Date).date()
        active = (str(po.PO_Status).upper() in ACTIVE_PO_STATUSES and not bool(po.Deletion_Flag)
                  and not bool(po.Completely_Delivered_Flag) and float(po.Open_Quantity) > 0)
        po_key = (str(po.PO_ID), str(po.PO_Item), str(po.Schedule_Line))
        eligibility = ("Ineligible — inactive or closed" if not active else
                       "Ineligible — overdue at analysis date" if receipt < analysis_date else
                       "Too late for earliest requirement; may support a later requirement" if need_date and receipt > need_date else
                       "Eligible by the earliest requirement date")
        rows.append({
            "Supplier": getattr(po, supplier_col), "Purchase_Order": str(po.PO_ID), "PO_Item": str(po.PO_Item),
            "Schedule_Line": str(po.Schedule_Line), "Expected_Receipt_Date": receipt,
            "Ordered_Quantity": float(po.Ordered_Quantity), "Received_Quantity": float(po.Received_Quantity),
            "Open_Quantity": float(po.Open_Quantity), "Quantity_Unit": str(po.Quantity_Unit),
            "PO_Status": str(po.PO_Status), "Supply_Eligibility": eligibility,
            "Actually_Allocated": po_key in allocated_keys,
            "Related_or_Potentially_Affected_Orders": related_orders or "No derived order relationship",
        })
    return pd.DataFrame(rows)


def order_investigation(order_id: str, order_item: str, sheets: dict[str, pd.DataFrame], shortage: pd.DataFrame,
                        exceptions: pd.DataFrame, analysis_date: date) -> dict[str, Any]:
    orders = build_orders_view(sheets, shortage, exceptions, analysis_date)
    order = orders[(orders.Sales_Order_ID.astype(str) == str(order_id)) &
                   (orders.Sales_Order_Item.astype(str) == str(order_item))]
    if order.empty:
        raise KeyError("Sales order item was not found in the loaded planning scope.")
    materials = shortage[(shortage.Source_Sales_Order_ID.astype(str) == str(order_id)) &
                         (shortage.Source_Sales_Order_Item.astype(str) == str(order_item))].copy() if not shortage.empty else shortage
    production = sheets["Production_Orders"]
    production = production[(production.Source_Sales_Order_ID.astype(str) == str(order_id)) &
                            (production.Source_Sales_Order_Item.astype(str) == str(order_item))].copy()
    po_frames = ([po_schedule_lines(r.Material_ID, r.Plant, sheets, shortage, analysis_date)
                  for r in materials[["Material_ID", "Plant"]].drop_duplicates().itertuples(index=False)]
                 if not materials.empty and {"Material_ID", "Plant"}.issubset(materials.columns) else [])
    pos = pd.concat(po_frames, ignore_index=True).drop_duplicates(["Purchase_Order", "PO_Item", "Schedule_Line"]) if po_frames else pd.DataFrame()
    backlog = bool((exceptions[(exceptions.Sales_Order_ID.astype(str) == str(order_id)) &
                               (exceptions.Sales_Order_Item.astype(str) == str(order_item))].Exception_Type == "PRODUCTION_BACKLOG").any())
    return {"order": order.iloc[0].to_dict(), "production_orders": production,
            "material_readiness": materials, "supplier_pos": pos, "production_backlog": backlog}
