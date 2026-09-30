"""Deterministic cockpit, aggregation, workflow and scenario tests."""
from collections import Counter
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from data.expanded_scenarios.generators import ALL_SCENARIOS
from src.ai_action_plan import build_order_ai_input
from src.exception_engine import build_exception_register
from src.order_summary import build_material_summary, build_order_summary
from src.shortage_engine import run_shortage_analysis
from src.workflow_state import apply_workflow_state, update_workflow_state
from src.workbook_reader import read_workbook

ROOT=Path(__file__).resolve().parents[1]; TEST_DATE=date(2026,9,25)

def analyzed(sid="S09"):
    path=ROOT/"data"/"expanded_scenarios"/"generated"/"small"/f"{sid}.xlsx"; sheets=read_workbook(path); result=run_shortage_analysis(sheets,TEST_DATE); return sheets,result,build_exception_register(sheets,result,TEST_DATE)

def test_exactly_25_scenarios_with_required_distribution():
    assert len(ALL_SCENARIOS)==25
    assert Counter(s.category for s in ALL_SCENARIOS.values())=={"small":9,"medium":8,"large":8}

def test_exception_ids_are_stable_and_unique():
    sheets,result,first=analyzed(); second=build_exception_register(sheets,result,TEST_DATE)
    assert first.Exception_ID.tolist()==second.Exception_ID.tolist(); assert first.Exception_ID.is_unique

def test_material_shortage_is_python_derived():
    _,result,exceptions=analyzed("S02"); shortage=exceptions[exceptions.Exception_Type=="MATERIAL_SHORTAGE"]
    assert not shortage.empty; assert (shortage.Shortage_Quantity>0).all(); assert set(shortage.Responsible_Role)=={"Procurement"}

def test_unscheduled_order_and_role():
    _,_,exceptions=analyzed("S06"); rows=exceptions[exceptions.Exception_Type=="UNSCHEDULED_ORDER"]
    assert len(rows) >= 1; assert set(rows.Responsible_Role)=={"Production Planning"}; assert rows.Material_ID.isna().all()


def test_unscheduled_order_ai_payload_has_exception_priority_without_material_row():
    sheets, result, exceptions = analyzed("S06")
    row = exceptions[
        (exceptions.Exception_Type == "UNSCHEDULED_ORDER")
        & exceptions.Sales_Order_ID.notna()
    ].iloc[0]
    payload = build_order_ai_input(
        str(row.Sales_Order_ID), str(row.Sales_Order_Item), exceptions,
        result.shortage_results, sheets,
    )["llm_payload"]
    assert payload["Primary_Exception_Type"] == "UNSCHEDULED_ORDER"
    assert payload["Python_Priority"] == row.Priority
    assert payload["Priority_Rule_ID"] == row.Priority_Rule_ID
    assert payload["Source_Sales_Order_ID"] == str(row.Sales_Order_ID)

def test_production_backlog_and_overdue_po_rules():
    _,_,backlog=analyzed("S03"); _,_,overdue=analyzed("S04")
    assert (backlog.Exception_Type=="PRODUCTION_BACKLOG").any(); assert (overdue.Exception_Type=="OVERDUE_INCOMING_PO").any()

def test_order_and_material_aggregations_preserve_roles_and_totals():
    sheets,_,exceptions=analyzed(); orders=build_order_summary(exceptions,sheets["Orders"]); materials=build_material_summary(exceptions)
    assert not orders.empty and not materials.empty; assert orders.Total_Shortage_Quantity.sum()>=0; assert orders.Responsible_Roles.str.len().min()>0

def test_workflow_update_does_not_change_calculated_fields():
    _,_,exceptions=analyzed(); state={}; eid=exceptions.iloc[0].Exception_ID; before=exceptions.drop(columns="Workflow_Status")
    update_workflow_state(state,eid,"IN_REVIEW"); after=apply_workflow_state(exceptions,state)
    pd.testing.assert_frame_equal(before,after.drop(columns="Workflow_Status")); assert after.loc[after.Exception_ID==eid,"Workflow_Status"].iloc[0]=="IN_REVIEW"

def test_order_ai_input_excludes_unrelated_orders():
    sheets,result,exceptions=analyzed(); row=exceptions[exceptions.Sales_Order_ID.notna()].iloc[0]; preview=build_order_ai_input(row.Sales_Order_ID,row.Sales_Order_Item,exceptions,result.shortage_results)
    assert preview["selected_order"]["Sales_Order_ID"]==row.Sales_Order_ID
    assert all(item.get("Exception_ID") in set(exceptions[exceptions.Sales_Order_ID==row.Sales_Order_ID].Exception_ID) for item in preview["verified_exceptions"])
    assert preview["human_review_required"] is True and preview["execution_status"]=="NOT_EXECUTED"

def test_exception_engine_does_not_cross_plants():
    path=ROOT/"data"/"expanded_scenarios"/"generated"/"medium"/"M05.xlsx"; sheets=read_workbook(path); result=run_shortage_analysis(sheets,TEST_DATE); exceptions=build_exception_register(sheets,result,TEST_DATE)
    assert all(len(set(group.Plant))==1 for _,group in exceptions.groupby(["Exception_ID"]))


def test_order_summary_counts_each_material_demand_once_across_exception_types():
    path = ROOT / "data" / "expanded_scenarios" / "generated" / "large" / "L04.xlsx"
    sheets = read_workbook(path)
    result = run_shortage_analysis(sheets, date(2026, 9, 28))
    exceptions = build_exception_register(sheets, result, date(2026, 9, 28))
    summary = build_order_summary(exceptions, sheets["Orders"])
    order_key = ("SOA0200001", "10")
    displayed = summary[
        (summary.Sales_Order_ID.astype(str) == order_key[0])
        & (summary.Sales_Order_Item.astype(str) == order_key[1])
    ].iloc[0].Total_Shortage_Quantity
    scope = result.shortage_results[
        (result.shortage_results.Source_Sales_Order_ID.astype(str) == order_key[0])
        & (result.shortage_results.Source_Sales_Order_Item.astype(str) == order_key[1])
    ]
    assert displayed == pytest.approx(scope.Shortage_Quantity.sum())


def test_overdue_only_material_signal_becomes_order_exception_and_payload_fact():
    path = ROOT / "data" / "expanded_scenarios" / "generated" / "large" / "L07.xlsx"
    sheets = read_workbook(path)
    result = run_shortage_analysis(sheets, date(2026, 9, 28))
    exceptions = build_exception_register(sheets, result, date(2026, 9, 28))
    scoped = exceptions[
        (exceptions.Sales_Order_ID.astype(str) == "SOA0230208")
        & (exceptions.Sales_Order_Item.astype(str) == "10")
        & (exceptions.Material_ID.astype(str) == "CB-3P-32A-V11")
    ]
    overdue = scoped[scoped.Exception_Type == "OVERDUE_INCOMING_SUPPLY"].iloc[0]
    assert overdue.Priority == "Low"
    assert overdue.Impact_Class == "MONITOR"
    payload = build_order_ai_input(
        "SOA0230208", "10", exceptions, result.shortage_results, sheets
    )["llm_payload"]
    review = next(
        item for item in payload["Verified_Exceptions"]
        if item["Exception_Type"] == "OVERDUE_INCOMING_SUPPLY"
        and item["Material_ID"] == "CB-3P-32A-V11"
    )
    assert review["Overdue_Incoming_Quantity"] == 41
    assert review["Directly_Pegged_To_Order"] is False
    assert payload["Payload_Completeness"]["expected_material_signal_count"] == payload["Payload_Completeness"]["covered_material_signal_count"]


def test_planned_completion_after_requested_delivery_is_detected():
    path = ROOT / "data" / "expanded_scenarios" / "generated" / "large" / "L04.xlsx"
    sheets = read_workbook(path)
    result = run_shortage_analysis(sheets, date(2026, 9, 28))
    exceptions = build_exception_register(sheets, result, date(2026, 9, 28))
    scoped = exceptions[
        (exceptions.Sales_Order_ID.astype(str) == "SOA0200019")
        & (exceptions.Sales_Order_Item.astype(str) == "10")
        & (exceptions.Exception_Type == "PLANNED_COMPLETION_AFTER_REQUESTED_DELIVERY")
    ]
    assert len(scoped) == 1
    facts = __import__("json").loads(scoped.iloc[0].Supporting_Facts)
    assert facts["Requested_Delivery_Date"] == "2026-10-03"
    assert facts["Planned_End_Date"] == "2026-10-12"
    assert facts["Days_After_Requested_Delivery"] == 9
