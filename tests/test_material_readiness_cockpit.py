"""Business cockpit, deterministic query and AI boundary tests."""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from src.analysis_service import analyze_workbook_content
from src.ai_action_plan import build_order_ai_input
from src.cockpit_service import (
    BUSINESS_EXCEPTION_LABELS, ai_candidate_exceptions, build_materials_view, build_orders_view,
    order_investigation, pending_scheduling, po_schedule_lines,
)


ROOT = Path(__file__).resolve().parents[1]
TEST_DATE = date(2026, 9, 25)


@pytest.fixture(scope="module")
def analyzed():
    return analyze_workbook_content((ROOT / "data/expanded_scenarios/generated/medium/M08.xlsx").read_bytes(), TEST_DATE)


def test_business_exception_labels_hide_technical_enums():
    assert BUSINESS_EXCEPTION_LABELS["MATERIAL_SHORTAGE"] == "Material Shortage"
    assert all("_" not in label for label in BUSINESS_EXCEPTION_LABELS.values())


def test_orders_view_contains_all_orders_not_only_exceptions(analyzed):
    view = build_orders_view(analyzed.sheets, analyzed.result.shortage_results, analyzed.exceptions, TEST_DATE)
    assert len(view) == len(analyzed.sheets["Orders"])
    assert {"Scheduling_Status", "Related_Production_Orders", "Total_Shortage", "Exception_Summary"} <= set(view)


def test_pending_scheduling_uses_open_positive_without_active_link(analyzed):
    frame = pending_scheduling(analyzed.sheets, TEST_DATE, analyzed.exceptions)
    assert set(frame.Scheduling_Status) <= {"Pending Scheduling"}
    assert (frame.Requested_Quantity > 0).all()
    assert frame.Reason.eq("No valid active linked production order.").all()


def test_completed_link_is_not_misclassified_as_pending_scheduling(analyzed):
    sheets = {name: frame.copy() for name, frame in analyzed.sheets.items()}
    production = sheets["Production_Orders"]
    row = production[production.Source_Sales_Order_ID.notna()].iloc[0]
    order_key = (str(row.Source_Sales_Order_ID), str(row.Source_Sales_Order_Item))
    same_order = (
        production.Source_Sales_Order_ID.astype(str).eq(order_key[0])
        & production.Source_Sales_Order_Item.astype(str).eq(order_key[1])
    )
    production.loc[same_order, "Remaining_Quantity"] = 0
    production.loc[same_order, "Order_Status"] = "CONFIRMED"
    pending = pending_scheduling(sheets, TEST_DATE, analyzed.exceptions)
    assert not (
        pending.Sales_Order_ID.astype(str).eq(order_key[0])
        & pending.Sales_Order_Item.astype(str).eq(order_key[1])
    ).any()
    view = build_orders_view(sheets, analyzed.result.shortage_results, analyzed.exceptions, TEST_DATE)
    selected = view[
        view.Sales_Order_ID.astype(str).eq(order_key[0])
        & view.Sales_Order_Item.astype(str).eq(order_key[1])
    ].iloc[0]
    assert selected.Scheduling_Status == "Production Complete / Awaiting Delivery"


def test_active_link_takes_precedence_over_another_completed_link(analyzed):
    sheets = {name: frame.copy() for name, frame in analyzed.sheets.items()}
    production = sheets["Production_Orders"]
    active = production[
        production.Order_Status.astype(str).isin({"CREATED", "RELEASED", "PARTIALLY_CONFIRMED"})
        & (pd.to_numeric(production.Remaining_Quantity) > 0)
        & production.Source_Sales_Order_ID.notna()
    ].iloc[0].copy()
    completed = active.copy()
    completed["Production_Order_ID"] = f"{active.Production_Order_ID}-DONE"
    completed["Order_Status"] = "COMPLETED"
    completed["Confirmed_Yield_Quantity"] = completed["Total_Quantity"]
    completed["Remaining_Quantity"] = 0
    sheets["Production_Orders"] = pd.concat(
        [production, pd.DataFrame([completed])], ignore_index=True
    )

    view = build_orders_view(sheets, analyzed.result.shortage_results, analyzed.exceptions, TEST_DATE)
    selected = view[
        view.Sales_Order_ID.astype(str).eq(str(active.Source_Sales_Order_ID))
        & view.Sales_Order_Item.astype(str).eq(str(active.Source_Sales_Order_Item))
    ].iloc[0]
    assert selected.Scheduling_Status == "Scheduled"


def test_material_view_and_po_schedule_line_detail(analyzed):
    materials = build_materials_view(analyzed.sheets, analyzed.result.shortage_results)
    assert {"Total_Required", "Usable_Inventory", "Eligible_Incoming_Supply", "Affected_Sales_Orders"} <= set(materials)
    first = materials.iloc[0]
    pos = po_schedule_lines(first.Material_ID, first.Plant, analyzed.sheets, analyzed.result.shortage_results, TEST_DATE)
    assert {"Purchase_Order", "PO_Item", "Schedule_Line", "Supply_Eligibility", "Actually_Allocated"} <= set(pos)
    assert "commit" not in " ".join(pos.get("Related_or_Potentially_Affected_Orders", []).astype(str)).lower()


def test_po_allocation_uses_exact_schedule_line_key():
    incoming = pd.DataFrame([
        {
            "PO_ID": "PO12", "PO_Item": "10", "Schedule_Line": "1", "Material_ID": "MAT1",
            "Plant": "1010", "Ordered_Quantity": 5, "Received_Quantity": 0, "Open_Quantity": 5,
            "Quantity_Unit": "EA", "Expected_Receipt_Date": pd.Timestamp("2026-09-26"),
            "PO_Status": "OPEN", "Deletion_Flag": False, "Completely_Delivered_Flag": False,
            "Supplier_ID": "SUP1",
        },
        {
            "PO_ID": "XPO12", "PO_Item": "10", "Schedule_Line": "1", "Material_ID": "MAT1",
            "Plant": "1010", "Ordered_Quantity": 5, "Received_Quantity": 0, "Open_Quantity": 5,
            "Quantity_Unit": "EA", "Expected_Receipt_Date": pd.Timestamp("2026-09-26"),
            "PO_Status": "OPEN", "Deletion_Flag": False, "Completely_Delivered_Flag": False,
            "Supplier_ID": "SUP2",
        },
    ])
    shortage = pd.DataFrame([{
        "Material_ID": "MAT1", "Plant": "1010", "Material_Need_Date": pd.Timestamp("2026-09-27"),
        "Allocated_PO_Lines": "XPO12/10/1:5", "Source_Sales_Order_ID": "SO1",
    }])

    lines = po_schedule_lines("MAT1", "1010", {"Incoming_PO": incoming}, shortage, TEST_DATE)
    allocation = lines.set_index("Purchase_Order")["Actually_Allocated"].to_dict()
    assert allocation == {"PO12": False, "XPO12": True}


def test_order_investigation_links_orders_materials_pos_and_production(analyzed):
    order = analyzed.sheets["Orders"].iloc[0]
    package = order_investigation(str(order.Sales_Order_ID), str(order.Sales_Order_Item), analyzed.sheets,
                                  analyzed.result.shortage_results, analyzed.exceptions, TEST_DATE)
    assert set(package) == {"order", "production_orders", "material_readiness", "supplier_pos", "production_backlog"}


def test_ai_sidebar_filter_narrows_orders_but_payload_keeps_all_order_exceptions(analyzed):
    exceptions = analyzed.exceptions
    grouped = exceptions.dropna(subset=["Sales_Order_ID"]).groupby(["Sales_Order_ID", "Sales_Order_Item"])
    order_key, order_rows = next((key, rows) for key, rows in grouped if len(rows) > 1)
    filtered = order_rows.iloc[[0]].copy()

    candidates = ai_candidate_exceptions(
        filtered, "All", analyzed.sheets, analyzed.result.shortage_results, TEST_DATE
    )
    assert len(candidates) == 1
    assert set(zip(candidates.Sales_Order_ID.astype(str), candidates.Sales_Order_Item.astype(str))) == {
        (str(order_key[0]), str(order_key[1]))
    }

    preview = build_order_ai_input(
        str(order_key[0]), str(order_key[1]), exceptions,
        analyzed.result.shortage_results, analyzed.sheets,
    )
    assert len(preview["llm_payload"]["Verified_Exceptions"]) == len(order_rows)
