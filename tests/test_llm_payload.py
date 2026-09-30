from datetime import date
import json
from pathlib import Path

import pytest

from src.ai_action_plan import (
    MAX_EXCEPTION_DETAILS, MAX_MATERIAL_DETAILS, MAX_PO_DETAILS, build_order_ai_input,
    inventory_coverage_message,
)
from src.analysis_service import ENGINE_VERSION, analysis_cache_key, analyze_workbook_content


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.llm_mock
def test_order_payload_is_bounded_and_requires_review():
    analyzed = analyze_workbook_content((ROOT / "data/expanded_scenarios/generated/large/L08.xlsx").read_bytes(), date(2026, 9, 25))
    row = analyzed.order_summary.iloc[0]
    payload = build_order_ai_input(str(row.Sales_Order_ID), str(row.Sales_Order_Item), analyzed.exceptions,
                                   analyzed.result.shortage_results, analyzed.sheets)
    assert len(payload["affected_material_facts"]) <= MAX_MATERIAL_DETAILS
    assert len(payload["related_po_details"]) <= MAX_PO_DETAILS
    assert payload["llm_payload"]["human_review_required"] is True
    assert payload["llm_payload"]["requires_human_approval"] is True
    assert payload["llm_payload"]["execution_status"] == "NOT_EXECUTED"
    for item in payload["llm_payload"]["Verified_Exceptions"]:
        assert "Workflow_Status" not in item
        assert "Responsible_Role" not in item
        assert item["Suggested_Responsible_Function"]
    assert payload["estimated_input_tokens"] > 0
    # The payload is passed directly to requests' json= parameter, so every
    # nested value must be serializable without a custom encoder.
    json.dumps(payload["llm_payload"])


def test_analysis_cache_identity_changes_with_content_date_and_engine():
    content = b"workbook bytes"
    first = analysis_cache_key(content, date(2026, 9, 25))
    assert first[2] == ENGINE_VERSION
    assert analysis_cache_key(content + b"!", date(2026, 9, 25))[0] != first[0]
    assert analysis_cache_key(content, date(2026, 9, 26))[1] != first[1]


def test_l04_payload_exposes_backlog_cause_and_exact_po_truncation():
    analyzed = analyze_workbook_content(
        (ROOT / "data/expanded_scenarios/generated/large/L04.xlsx").read_bytes(),
        date(2026, 9, 27),
    )
    payload = build_order_ai_input(
        "SOA0200001", "10", analyzed.exceptions,
        analyzed.result.shortage_results, analyzed.sheets,
    )["llm_payload"]
    assert payload["Order_Exception_Count"] == 2
    assert payload["Order_Has_Material_Shortage"] is False
    assert payload["additional_exception_count"] == 0
    assert payload["additional_po_line_count"] == 2
    backlog, late = payload["Verified_Exceptions"]
    assert backlog["Exception_Type"] == "PRODUCTION_BACKLOG"
    assert backlog["Production_Order_Status"] == "PARTIALLY_CONFIRMED"
    assert backlog["Planned_End_Date"] == "2026-09-24"
    assert backlog["Remaining_Quantity"] == 1
    assert late["Exception_Type"] == "LATE_INCOMING_SUPPLY"
    assert late["Inventory_Allocated"] == late["Required_Quantity"] == 2


def test_verified_exception_bound_matches_output_token_budget_strategy():
    assert MAX_EXCEPTION_DETAILS == 8


def test_inventory_coverage_message_is_deterministic_and_only_for_full_coverage():
    covered = {
        "Exception_Type": "LATE_INCOMING_SUPPLY", "Required_Quantity": 2,
        "Inventory_Allocated": 2, "Shortage_Quantity": 0, "Quantity_Unit": "EA",
    }
    assert inventory_coverage_message(covered) == (
        "Inventory covers the full requirement: 2 of 2 EA is allocated in the deterministic calculation."
    )
    assert inventory_coverage_message({**covered, "Inventory_Allocated": 1}) is None
