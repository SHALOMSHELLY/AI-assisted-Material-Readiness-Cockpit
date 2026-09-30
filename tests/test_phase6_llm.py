"""Phase 6 security-boundary tests."""

import json
import subprocess
import sys
from copy import deepcopy
from datetime import date
from pathlib import Path

import pytest
import requests
from streamlit.testing.v1 import AppTest

from config.settings import (
    DEFAULT_OPENROUTER_MODEL, LLM_MAX_OUTPUT_TOKENS, LLM_REQUEST_TIMEOUT_SECONDS,
    MODEL_PRICING_USD_PER_MILLION_TOKENS,
)
from src.llm_client import (
    EXPEDITE_ACTION_TYPE, LLMConfigurationError, LLMRequestError, LLMResult,
    canonicalize_llm_output, displayed_cost, estimate_cost_usd, generate_explanation,
    parse_llm_output,
)
from src.llm_prompt import (
    ALLOWED_ACTION_TYPES, EVIDENCE_FIELDS, FIXED_HUMAN_REVIEW_NOTICE,
    MISSING_INFORMATION, MISSING_INFORMATION_CODES, PROMPT_VERSION, SCHEMA_VERSION,
    build_messages, build_output_schema, build_response_format, build_structured_input,
)
from src.shortage_engine import run_shortage_analysis
from src.ui_state import llm_cache_key, upload_signature
from src.workbook_reader import read_workbook


ROOT = Path(__file__).resolve().parents[1]
TEST_DATE = date(2026, 9, 25)
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture(scope="module")
def facts():
    result = run_shortage_analysis(read_workbook(ROOT / "test_data" / "sample_workbook.xlsx"), TEST_DATE)
    return build_structured_input(result.shortage_results.iloc[0])


@pytest.fixture(scope="module")
def a02_facts():
    """Build a deterministic shortage case without the retired Phase 4 workbook."""

    result = run_shortage_analysis(
        read_workbook(ROOT / "test_data" / "sample_workbook.xlsx"), TEST_DATE
    )
    structured = build_structured_input(result.shortage_results.iloc[0])
    structured.update({
        "Unrestricted_Inventory": 5,
        "Usable_Inventory": 5,
        "Eligible_Incoming_Quantity": 0,
        "Late_Incoming_Quantity": 0,
        "Overdue_Incoming_Quantity": 0,
        "Total_Available": 5,
        "Inventory_Allocated": 5,
        "Incoming_PO_Allocated": 0,
        "Shortage_Quantity": 11,
        "Next_Receipt_Date": None,
        "Python_Priority": "High",
        "Priority_Rule_ID": "P2",
    })
    return structured


def valid_output(facts):
    return {
        "priority_summary": ":Low.  Priority is Low.",
        "explanation": ":.  Supply covers demand.",
        "python_priority": facts["Python_Priority"],
        "priority_rule_id": facts["Priority_Rule_ID"],
        "exception_reviews": [],
        "recommended_actions": [{
            "action_type": "Take no immediate action when supply is sufficient",
            "action": ":.  No immediate action is needed.",
            "evidence": [{"exception_id": None, "field": "Shortage_Quantity", "value": facts["Shortage_Quantity"], "unit": facts["Quantity_Unit"]}],
            "requires_human_approval": True,
            "execution_status": "NOT_EXECUTED",
        }],
        "missing_information_codes": ["SUPPLIER_CONFIRMATION"],
    }


def expedite_output(facts, evidence_fields):
    output = valid_output(facts)
    output["recommended_actions"][0] = {
        "action_type": EXPEDITE_ACTION_TYPE,
        "action": ":.  Check whether an existing delivery can be expedited.",
        "evidence": [
            {
                "exception_id": None,
                "field": field,
                "value": facts[field],
                "unit": facts["Quantity_Unit"] if field.endswith("_Quantity") else None,
            }
            for field in evidence_fields
        ],
        "requires_human_approval": True,
        "execution_status": "NOT_EXECUTED",
    }
    return output


def parse(output, facts):
    return parse_llm_output(json.dumps(output, ensure_ascii=False), facts)


def mocked_generation(monkeypatch, facts, payload):
    class FakeResponse:
        status_code = 200
        text = "ok"
        def raise_for_status(self): return None
        def json(self): return payload
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-real")
    monkeypatch.setattr("src.llm_client.load_dotenv", lambda: False)
    monkeypatch.setattr("src.llm_client.requests.post", lambda *args, **kwargs: FakeResponse())
    return generate_explanation(facts)


def test_structured_input_contains_only_one_calculated_row(facts):
    assert facts["Required_Quantity"] == 16
    assert facts["Shortage_Quantity"] == 0
    assert facts["Python_Priority"] == "Low"
    assert facts["Priority_Rule_ID"] == "P4"
    assert set(facts) == set(EVIDENCE_FIELDS)
    assert "Orders" not in facts and "Supplier_ID" not in facts


def test_structured_input_normalizes_evidence_types():
    row = {
        "Analysis_Date": TEST_DATE,
        "Production_Order_ID": 3001,
        "Production_Order_Item": 10,
        "Source_Sales_Order_ID": 1001,
        "Source_Sales_Order_Item": 20,
        "Product_ID": 9001,
        "Material_ID": 7001,
        "Plant": 1010,
        "Material_Need_Date": TEST_DATE,
        "Required_Quantity": 16,
        "Quantity_Unit": "EA",
        "Unrestricted_Inventory": 0,
        "Safety_Stock": 0,
        "Usable_Inventory": 0,
        "Eligible_Incoming_Quantity": 0,
        "Late_Incoming_Quantity": 0,
        "Overdue_Incoming_Quantity": 0,
        "Total_Available": 0,
        "Inventory_Allocated": 0,
        "Incoming_PO_Allocated": 0,
        "Shortage_Quantity": 16,
        "Next_Receipt_Date": None,
        "Priority": "High",
        "Priority_Rule_ID": "P2",
        "Calculation_Explanation": "fixed",
    }
    normalized = build_structured_input(row)
    assert normalized["Production_Order_Item"] == "10"
    assert normalized["Plant"] == "1010"
    assert normalized["Analysis_Date"] == "2026-09-25"
    assert normalized["Next_Receipt_Date"] is None
    assert normalized["Late_Incoming_Quantity"] == 0.0
    assert isinstance(normalized["Late_Incoming_Quantity"], float)


def test_prompt_explicitly_requires_units_for_zero_quantities(facts):
    system = build_messages(facts)[0]["content"]
    assert "including a zero quantity" in system
    assert "including Days_After_Requested_Delivery, set unit to null" in system
    assert "Identifier and item fields are strings" in system


def test_prompt_prohibits_recalculation_invention_and_execution(facts):
    system = build_messages(facts)[0]["content"]
    assert "Never recalculate" in system
    assert "Never invent" in system
    assert "Never claim that an action has occurred" in system
    assert "Eligible_Incoming_Quantity is already timely" in system
    assert "Prefer one fully supported action" in system
    assert "Do not recommend production-order rescheduling" in system
    assert "Every Exception_ID must appear" in system
    assert "subjective severity words" in system
    assert "PRODUCTION_BACKLOG" in system and "Remaining_Quantity" in system


def multi_exception_facts(facts):
    structured = dict(facts)
    structured.update({
        "Primary_Exception_Type": "LATE_INCOMING_SUPPLY",
        "Order_Has_Material_Shortage": False,
        "Order_Has_Late_Or_Overdue_Supply": True,
        "Verified_Exceptions": [
            {
                "Exception_ID": "EX-LATE-1", "Exception_Type": "LATE_INCOMING_SUPPLY",
                "Material_ID": "MAT-LATE", "Priority": "Critical",
                "Material_Need_Date": "2026-09-21", "Quantity_Unit": "EA",
                "Shortage_Quantity": 0.0, "Late_Incoming_Quantity": 10.0,
                "Next_Receipt_Date": "2026-09-27", "Production_Order_ID": "PR1",
                "Required_Quantity": 5.0, "Inventory_Allocated": 5.0,
                "Overdue_Incoming_Quantity": 0.0, "Requested_Delivery_Date": None,
                "Planned_Start_Date": None, "Planned_End_Date": None,
                "Days_After_Requested_Delivery": None, "Impact_Class": "MONITOR",
                "Direct_Order_Impact": False, "Supply_Relationship": "MATERIAL_PLANT_POOL",
                "Directly_Pegged_To_Order": False,
            },
            {
                "Exception_ID": "EX-BACKLOG-1", "Exception_Type": "PRODUCTION_BACKLOG",
                "Material_ID": None, "Priority": "Critical",
                "Material_Need_Date": "2026-09-24", "Quantity_Unit": "EA",
                "Shortage_Quantity": 0.0, "Late_Incoming_Quantity": None,
                "Next_Receipt_Date": None, "Production_Order_ID": "PR1",
                "Overdue_Incoming_Quantity": None, "Requested_Delivery_Date": None,
                "Planned_Start_Date": "2026-09-21", "Planned_End_Date": "2026-09-24",
                "Days_After_Requested_Delivery": None, "Impact_Class": "BLOCKING",
                "Direct_Order_Impact": True, "Supply_Relationship": None,
                "Directly_Pegged_To_Order": None,
            },
        ],
        "Required_Missing_Information_Codes": [
            "CROSS_ORDER_SUPPLY_DEPENDENCIES", "PRODUCTION_SCHEDULE_CONSTRAINTS",
            "SUPPLIER_CONFIRMATION",
        ],
    })
    structured["Python_Priority"] = "Critical"
    structured["Priority_Rule_ID"] = "EX-P1"
    structured["Shortage_Quantity"] = 0.0
    structured["Late_Incoming_Quantity"] = 10.0
    return structured


def multi_exception_output(structured):
    late, backlog = structured["Verified_Exceptions"]
    def review(item, finding, recommendation):
        return {
            "exception_id": item["Exception_ID"],
            "exception_type": item["Exception_Type"],
            "material_id": item["Material_ID"],
            "priority": item["Priority"],
            "material_need_date": item["Material_Need_Date"],
            "quantity_unit": item["Quantity_Unit"],
            "shortage_quantity": item["Shortage_Quantity"],
            "late_incoming_quantity": item["Late_Incoming_Quantity"],
            "overdue_incoming_quantity": item.get("Overdue_Incoming_Quantity"),
            "next_receipt_date": item["Next_Receipt_Date"],
            "requested_delivery_date": item.get("Requested_Delivery_Date"),
            "planned_start_date": item.get("Planned_Start_Date"),
            "planned_end_date": item.get("Planned_End_Date"),
            "days_after_requested_delivery": item.get("Days_After_Requested_Delivery"),
            "impact_class": item["Impact_Class"],
            "direct_order_impact": item["Direct_Order_Impact"],
            "supply_relationship": item.get("Supply_Relationship"),
            "directly_pegged_to_order": item.get("Directly_Pegged_To_Order"),
            "finding": finding,
            "recommended_review": recommendation,
            "requires_human_approval": True,
            "execution_status": "NOT_EXECUTED",
        }
    return {
        "priority_summary": "The primary exception is Critical late incoming supply.",
        "explanation": "Demand is covered, while late supply and production backlog require review.",
        "python_priority": "Critical",
        "priority_rule_id": "EX-P1",
        "exception_reviews": [
            review(late, "Inventory covers the full requirement and 10 EA is late.", "Confirm the supplier date and review other-order dependency."),
            review(backlog, "Production order PR1 remains backlogged after 2026-09-24.", "Review the production-order status and constraints."),
        ],
        "recommended_actions": [
            {
                "action_type": "Request missing data",
                "action": "Request supplier confirmation and cross-order impact review for MAT-LATE.",
                "evidence": [{"exception_id": "EX-LATE-1", "field": "Late_Incoming_Quantity", "value": 10.0, "unit": "EA"}],
                "requires_human_approval": True, "execution_status": "NOT_EXECUTED",
            },
            {
                "action_type": "Escalate to production planning",
                "action": "Request production-planning review of backlog for PR1.",
                "evidence": [{"exception_id": "EX-BACKLOG-1", "field": "Production_Order_ID", "value": "PR1", "unit": None}],
                "requires_human_approval": True, "execution_status": "NOT_EXECUTED",
            },
        ],
        "missing_information_codes": [
            "SUPPLIER_CONFIRMATION", "CROSS_ORDER_SUPPLY_DEPENDENCIES",
            "PRODUCTION_SCHEDULE_CONSTRAINTS",
        ],
    }


def test_parser_accepts_actions_covering_late_and_backlog_exceptions(facts):
    structured = multi_exception_facts(facts)
    output = multi_exception_output(structured)
    assert parse(output, structured) == output


def test_canonicalizer_replaces_model_actions_evidence_units_and_codes(facts):
    structured = multi_exception_facts(facts)
    output = multi_exception_output(structured)
    output["python_priority"] = "Low"
    output["priority_rule_id"] = "wrong"
    output["recommended_actions"] = [{
        "action_type": "Take no immediate action when supply is sufficient",
        "action": "Incorrect model proposal.",
        "evidence": [{
            "exception_id": "EX-LATE-1", "field": "Late_Incoming_Quantity",
            "value": 999, "unit": "KG",
        }],
        "requires_human_approval": True,
        "execution_status": "NOT_EXECUTED",
    }]
    output["missing_information_codes"] = []

    canonical = json.loads(canonicalize_llm_output(json.dumps(output), structured))
    parsed = parse_llm_output(json.dumps(canonical), structured)

    assert parsed["python_priority"] == structured["Python_Priority"]
    assert parsed["priority_rule_id"] == structured["Priority_Rule_ID"]
    assert {item["action_type"] for item in parsed["recommended_actions"]} == {
        "Request missing data", "Escalate to production planning",
    }
    assert parsed["missing_information_codes"] == structured["Required_Missing_Information_Codes"]
    for action in parsed["recommended_actions"]:
        for evidence in action["evidence"]:
            if evidence["field"].endswith("_Quantity"):
                assert evidence["unit"] == "EA"
            else:
                assert evidence["unit"] is None


def test_canonicalizer_copies_exception_facts_but_keeps_model_narratives(facts):
    structured = multi_exception_facts(facts)
    output = multi_exception_output(structured)
    output["exception_reviews"][0]["shortage_quantity"] = 999
    output["exception_reviews"][0]["quantity_unit"] = "KG"
    output["exception_reviews"][0]["finding"] = "Model-authored bounded finding."

    canonical = json.loads(canonicalize_llm_output(json.dumps(output), structured))

    assert canonical["exception_reviews"][0]["shortage_quantity"] == 0.0
    assert canonical["exception_reviews"][0]["quantity_unit"] == "EA"
    assert canonical["exception_reviews"][0]["finding"] == "Model-authored bounded finding."


def test_parser_rejects_recommended_actions_that_omit_backlog(facts):
    structured = multi_exception_facts(facts)
    output = multi_exception_output(structured)
    output["recommended_actions"].pop()
    with pytest.raises(LLMRequestError, match="covering every verified exception"):
        parse(output, structured)


def test_parser_requires_cross_order_dependencies_for_covered_late_supply(facts):
    structured = multi_exception_facts(facts)
    output = multi_exception_output(structured)
    output["missing_information_codes"].remove("CROSS_ORDER_SUPPLY_DEPENDENCIES")
    with pytest.raises(LLMRequestError, match="exactly match"):
        parse(output, structured)


def test_parser_does_not_fail_a_factually_valid_result_over_coverage_wording(facts):
    structured = multi_exception_facts(facts)
    output = multi_exception_output(structured)
    output["exception_reviews"][0]["finding"] = "The shortage is zero and 10 EA is late."
    assert parse(output, structured) == output


def test_parser_rejects_backlog_covered_by_wrong_action_type(facts):
    structured = multi_exception_facts(facts)
    output = multi_exception_output(structured)
    output["recommended_actions"][1]["action_type"] = "Request missing data"
    with pytest.raises(LLMRequestError, match="production-planning review action"):
        parse(output, structured)


def test_parser_rejects_subjective_quantity_severity(facts):
    output = valid_output(facts)
    output["explanation"] = "There is a significant quantity of supply."
    with pytest.raises(LLMRequestError, match="subjective severity"):
        parse(output, facts)


def test_parser_rejects_delay_claim_without_date_change_evidence(facts):
    output = valid_output(facts)
    output["explanation"] = "The supplier delivery is delayed."
    with pytest.raises(LLMRequestError, match="date-change evidence"):
        parse(output, facts)


def test_parser_allows_delayed_planned_completion_when_schedule_dates_support_it(facts):
    output = valid_output(facts)
    output["explanation"] = (
        "Review production planning to address the delayed planned completion date."
    )
    assert parse(output, facts) == output


@pytest.mark.parametrize("claim", [
    "The selected order has no material shortage.",
    "No material shortages exist overall.",
    "Supply is sufficient for the selected order.",
])
def test_parser_rejects_order_supply_sufficient_claim_when_any_shortage_exists(facts, claim):
    structured = dict(facts)
    structured["Order_Has_Material_Shortage"] = True
    output = valid_output(structured)
    output["explanation"] = claim
    output["recommended_actions"][0] = {
        "action_type": "Escalate to procurement",
        "action": "Escalate the verified order shortage for human investigation.",
        "evidence": [{
            "exception_id": None, "field": "Shortage_Quantity",
            "value": structured["Shortage_Quantity"], "unit": structured["Quantity_Unit"],
        }],
        "requires_human_approval": True, "execution_status": "NOT_EXECUTED",
    }
    with pytest.raises(LLMRequestError, match="supply-sufficient"):
        parse(output, structured)


def test_a02_real_facts_reject_unsupported_expedite_action(a02_facts):
    assert a02_facts["Required_Quantity"] == 16
    assert a02_facts["Usable_Inventory"] == 5
    assert a02_facts["Shortage_Quantity"] == 11
    assert a02_facts["Python_Priority"] == "High"
    assert a02_facts["Priority_Rule_ID"] == "P2"
    assert all(a02_facts[field] == 0 for field in (
        "Eligible_Incoming_Quantity", "Late_Incoming_Quantity", "Overdue_Incoming_Quantity"
    ))
    output = expedite_output(a02_facts, ["Production_Order_ID", "Material_ID", "Shortage_Quantity", "Python_Priority"])
    with pytest.raises(LLMRequestError):
        parse(output, a02_facts)


def test_zero_incoming_is_not_supported_by_shortage_and_priority_evidence(a02_facts):
    output = expedite_output(a02_facts, ["Shortage_Quantity", "Python_Priority"])
    with pytest.raises(LLMRequestError, match="no positive late or overdue"):
        parse(output, a02_facts)


@pytest.mark.parametrize("field", ["Late_Incoming_Quantity", "Overdue_Incoming_Quantity"])
def test_expedite_passes_with_positive_cited_incoming_field(a02_facts, field):
    supported = dict(a02_facts)
    supported[field] = 6
    assert parse(expedite_output(supported, [field]), supported)


def test_eligible_on_time_supply_alone_does_not_support_expedite(a02_facts):
    unsupported = dict(a02_facts)
    unsupported["Eligible_Incoming_Quantity"] = 10
    with pytest.raises(LLMRequestError, match="eligible on-time supply alone"):
        parse(expedite_output(unsupported, ["Eligible_Incoming_Quantity"]), unsupported)


def test_zero_shortage_rejects_expedite_even_with_late_supply(a02_facts):
    unsupported = dict(a02_facts)
    unsupported["Shortage_Quantity"] = 0
    unsupported["Late_Incoming_Quantity"] = 10
    with pytest.raises(LLMRequestError, match="shortage is zero"):
        parse(expedite_output(unsupported, ["Late_Incoming_Quantity"]), unsupported)


def test_positive_supply_without_incoming_evidence_is_rejected(a02_facts):
    supported = dict(a02_facts)
    supported["Late_Incoming_Quantity"] = 6
    with pytest.raises(LLMRequestError):
        parse(expedite_output(supported, ["Shortage_Quantity"]), supported)


def test_citing_zero_incoming_field_does_not_support_positive_other_field(a02_facts):
    supported = dict(a02_facts)
    supported["Late_Incoming_Quantity"] = 6
    with pytest.raises(LLMRequestError, match="positive incoming-supply field"):
        parse(expedite_output(supported, ["Eligible_Incoming_Quantity"]), supported)


def test_expedite_wrong_evidence_value_still_uses_general_validation(a02_facts):
    supported = dict(a02_facts)
    supported["Eligible_Incoming_Quantity"] = 10
    output = expedite_output(supported, ["Eligible_Incoming_Quantity"])
    output["recommended_actions"][0]["evidence"][0]["value"] = 9
    with pytest.raises(LLMRequestError, match="Python"):
        parse(output, supported)


def test_expedite_wrong_evidence_unit_still_uses_general_validation(a02_facts):
    supported = dict(a02_facts)
    supported["Overdue_Incoming_Quantity"] = 4
    output = expedite_output(supported, ["Overdue_Incoming_Quantity"])
    output["recommended_actions"][0]["evidence"][0]["unit"] = "KG"
    with pytest.raises(LLMRequestError):
        parse(output, supported)


@pytest.mark.parametrize("invalid_value", [None, True, "6"])
def test_none_bool_and_string_are_not_positive_incoming_supply(a02_facts, invalid_value):
    unsupported = dict(a02_facts)
    unsupported["Late_Incoming_Quantity"] = invalid_value
    output = expedite_output(unsupported, ["Shortage_Quantity"])
    with pytest.raises(LLMRequestError):
        parse(output, unsupported)


def test_positive_shortage_rejects_no_action(a02_facts):
    with pytest.raises(LLMRequestError):
        parse(valid_output(a02_facts), a02_facts)


@pytest.mark.parametrize("action_type", [
    "Review production-order rescheduling",
    "Review material allocation across production orders",
    "Check whether an approved alternative material exists",
])
def test_single_row_rejects_actions_requiring_missing_business_context(a02_facts, action_type):
    output = valid_output(a02_facts)
    output["recommended_actions"][0]["action_type"] = action_type
    with pytest.raises(LLMRequestError, match="Python"):
        parse(output, a02_facts)


def test_zero_shortage_rejects_procurement_escalation(facts):
    output = valid_output(facts)
    output["recommended_actions"][0]["action_type"] = "Escalate to procurement"
    with pytest.raises(LLMRequestError):
        parse(output, facts)


def test_strict_schema_has_exactness_and_single_value_enums():
    schema = build_output_schema()
    assert schema["additionalProperties"] is False
    action = schema["properties"]["recommended_actions"]["items"]
    evidence = action["properties"]["evidence"]["items"]
    assert action["additionalProperties"] is False
    assert evidence["additionalProperties"] is False
    assert action["properties"]["action_type"]["enum"] == ALLOWED_ACTION_TYPES
    assert evidence["properties"]["field"]["enum"] == EVIDENCE_FIELDS
    assert action["properties"]["requires_human_approval"] == {"type": "boolean", "enum": [True]}
    assert "Review production-order rescheduling" not in ALLOWED_ACTION_TYPES
    review = schema["properties"]["exception_reviews"]["items"]
    assert {"overdue_incoming_quantity", "impact_class", "requested_delivery_date"} <= set(review["properties"])
    assert action["properties"]["execution_status"] == {"type": "string", "enum": ["NOT_EXECUTED"]}


def test_remote_schema_omits_known_incompatible_keywords_and_uses_any_of():
    schema = build_output_schema()
    encoded = json.dumps(schema)
    for keyword in ('"minLength"', '"minItems"', '"uniqueItems"', '"const"'):
        assert keyword not in encoded
    evidence = schema["properties"]["recommended_actions"]["items"]["properties"]["evidence"]["items"]
    assert evidence["properties"]["value"]["anyOf"] == [
        {"type": "string"}, {"type": "number"}, {"type": "null"}
    ]
    assert evidence["properties"]["unit"]["anyOf"] == [{"type": "string"}, {"type": "null"}]


def test_response_format_is_strict_json_schema():
    response_format = build_response_format()
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True


def test_parser_accepts_valid_structured_output(facts):
    output = valid_output(facts)
    assert parse(output, facts) == output


@pytest.mark.parametrize("missing", [
    "priority_summary", "explanation", "python_priority", "priority_rule_id",
    "exception_reviews", "recommended_actions", "missing_information_codes",
])
def test_parser_rejects_each_missing_top_level_field(facts, missing):
    output = valid_output(facts)
    output.pop(missing)
    with pytest.raises(LLMRequestError, match="|exactly match"):
        parse(output, facts)


def test_parser_rejects_extra_top_level_field(facts):
    output = valid_output(facts)
    output["human_review_notice"] = "model-controlled"
    with pytest.raises(LLMRequestError):
        parse(output, facts)


@pytest.mark.parametrize("field", ["priority_summary", "explanation", "python_priority", "priority_rule_id"])
def test_parser_rejects_empty_required_text(facts, field):
    output = valid_output(facts)
    output[field] = " "
    with pytest.raises(LLMRequestError):
        parse(output, facts)


def test_parser_rejects_wrong_python_priority(facts):
    output = valid_output(facts)
    output["python_priority"] = "Critical"
    with pytest.raises(LLMRequestError):
        parse(output, facts)


def test_parser_rejects_wrong_priority_rule(facts):
    output = valid_output(facts)
    output["priority_rule_id"] = "P1"
    with pytest.raises(LLMRequestError):
        parse(output, facts)


def test_parser_rejects_disallowed_action_type(facts):
    output = valid_output(facts)
    output["recommended_actions"][0]["action_type"] = "Create purchase order"
    with pytest.raises(LLMRequestError):
        parse(output, facts)


def test_parser_rejects_empty_action_text(facts):
    output = valid_output(facts)
    output["recommended_actions"][0]["action"] = ""
    with pytest.raises(LLMRequestError):
        parse(output, facts)


def test_parser_rejects_malicious_execution_claim_in_action_text(facts):
    output = valid_output(facts)
    output["recommended_actions"][0]["action"] = ":.  A purchase order was created."
    with pytest.raises(LLMRequestError, match="already occurred"):
        parse(output, facts)


def test_parser_rejects_missing_evidence(facts):
    output = valid_output(facts)
    output["recommended_actions"][0]["evidence"] = []
    with pytest.raises(LLMRequestError, match="Evidence"):
        parse(output, facts)


def test_parser_rejects_unknown_evidence_field(facts):
    output = valid_output(facts)
    output["recommended_actions"][0]["evidence"][0]["field"] = "Supplier_Name"
    with pytest.raises(LLMRequestError):
        parse(output, facts)


def test_parser_rejects_wrong_evidence_value(facts):
    output = valid_output(facts)
    output["recommended_actions"][0]["evidence"][0]["value"] = 999
    with pytest.raises(LLMRequestError, match="Python"):
        parse(output, facts)


def test_parser_rejects_wrong_quantity_evidence_unit(facts):
    output = valid_output(facts)
    output["recommended_actions"][0]["evidence"][0]["unit"] = "KG"
    with pytest.raises(LLMRequestError):
        parse(output, facts)


def test_parser_requires_null_unit_for_non_quantity_evidence(facts):
    output = valid_output(facts)
    output["recommended_actions"][0]["evidence"][0] = {"exception_id": None, "field": "Plant", "value": facts["Plant"], "unit": "EA"}
    with pytest.raises(LLMRequestError):
        parse(output, facts)


def test_parser_treats_days_after_requested_delivery_as_unitless_numeric_evidence(facts):
    schedule_facts = dict(facts)
    schedule_facts["Days_After_Requested_Delivery"] = 9
    output = valid_output(schedule_facts)
    output["recommended_actions"][0]["evidence"][0] = {
        "exception_id": None,
        "field": "Days_After_Requested_Delivery",
        "value": 9,
        "unit": None,
    }
    parsed = parse(output, schedule_facts)
    assert parsed["recommended_actions"][0]["evidence"][0]["unit"] is None


def test_parser_rejects_extra_evidence_field(facts):
    output = valid_output(facts)
    output["recommended_actions"][0]["evidence"][0]["note"] = "invented"
    with pytest.raises(LLMRequestError, match="Evidence"):
        parse(output, facts)


def test_parser_rejects_wrong_human_approval_flag(facts):
    output = valid_output(facts)
    output["recommended_actions"][0]["requires_human_approval"] = False
    with pytest.raises(LLMRequestError):
        parse(output, facts)


def test_parser_rejects_wrong_execution_status(facts):
    output = valid_output(facts)
    output["recommended_actions"][0]["execution_status"] = "EXECUTED"
    with pytest.raises(LLMRequestError, match="must not claim"):
        parse(output, facts)


def test_parser_rejects_extra_action_field(facts):
    output = valid_output(facts)
    output["recommended_actions"][0]["automatic"] = True
    with pytest.raises(LLMRequestError):
        parse(output, facts)


def test_parser_rejects_unknown_missing_information_code(facts):
    output = valid_output(facts)
    output["missing_information_codes"] = ["UNKNOWN"]
    with pytest.raises(LLMRequestError):
        parse(output, facts)


def test_parser_rejects_duplicate_missing_information_code(facts):
    output = valid_output(facts)
    output["missing_information_codes"] = ["SUPPLIER_CONFIRMATION", "SUPPLIER_CONFIRMATION"]
    with pytest.raises(LLMRequestError):
        parse(output, facts)


def test_missing_information_codes_have_english_local_labels():
    assert list(MISSING_INFORMATION) == MISSING_INFORMATION_CODES
    assert all(label and " / " not in label for label in MISSING_INFORMATION.values())


def test_human_review_notice_is_fixed_local_text_not_schema_field():
    assert "SAP" in FIXED_HUMAN_REVIEW_NOTICE
    assert "cannot modify SAP or create purchase orders" in FIXED_HUMAN_REVIEW_NOTICE
    assert "human_review_notice" not in build_output_schema()["properties"]


def test_missing_key_fails_without_http_call(monkeypatch, facts):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr("src.llm_client.load_dotenv", lambda: False)
    monkeypatch.setattr("src.llm_client.requests.post", lambda *a, **k: pytest.fail("HTTP must not be called"))
    with pytest.raises(LLMConfigurationError):
        generate_explanation(facts)


def test_client_sends_strict_schema_token_limit_and_timeout(monkeypatch, facts):
    output = valid_output(facts)
    captured = {}

    class FakeResponse:
        status_code = 200
        text = "ok"
        def raise_for_status(self): return None
        def json(self):
            return {"model": "test/model", "choices": [{"message": {"content": json.dumps(output, ensure_ascii=False)}}], "usage": {"total_tokens": 42}}

    def fake_post(*args, **kwargs):
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-real")
    monkeypatch.setattr("src.llm_client.load_dotenv", lambda: False)
    monkeypatch.setattr("src.llm_client.requests.post", fake_post)
    result = generate_explanation(facts)
    assert result.total_tokens == 42
    assert captured["timeout"] == LLM_REQUEST_TIMEOUT_SECONDS
    assert captured["json"]["max_tokens"] == LLM_MAX_OUTPUT_TOKENS == 6000
    assert captured["json"]["response_format"]["type"] == "json_schema"
    assert captured["json"]["response_format"]["json_schema"]["strict"] is True
    assert captured["json"]["provider"]["require_parameters"] is True
    assert captured["json"]["usage"] == {"include": True}


def test_client_reports_output_token_truncation_before_json_parsing(monkeypatch, facts):
    payload = {
        "model": "openai/gpt-4.1-mini",
        "choices": [{"finish_reason": "length", "message": {"content": '{"priority_summary":'}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 6000, "total_tokens": 6100},
    }
    with pytest.raises(LLMRequestError, match="output-token limit") as captured:
        mocked_generation(monkeypatch, facts, payload)
    assert captured.value.response_metadata["output_tokens"] == 6000


def test_usage_tokens_generation_id_and_exact_cost_are_read(monkeypatch, facts):
    payload = {
        "id": "gen-test-123", "model": "openai/gpt-4.1-mini",
        "choices": [{"message": {"content": json.dumps(valid_output(facts), ensure_ascii=False)}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 25, "total_tokens": 125, "cost": 0.00008},
    }
    result = mocked_generation(monkeypatch, facts, payload)
    assert result.generation_id == "gen-test-123"
    assert result.input_tokens == 100
    assert result.output_tokens == 25
    assert result.total_tokens == 125
    assert result.exact_cost_usd == pytest.approx(0.00008)
    assert result.estimated_cost_usd == pytest.approx(0.00008)


def test_missing_cost_keeps_exact_none_but_estimates(monkeypatch, facts):
    payload = {
        "model": "openai/gpt-4.1-mini",
        "choices": [{"message": {"content": json.dumps(valid_output(facts), ensure_ascii=False)}}],
        "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000, "total_tokens": 2_000_000},
    }
    result = mocked_generation(monkeypatch, facts, payload)
    assert result.generation_id is None
    assert result.exact_cost_usd is None
    assert result.estimated_cost_usd == pytest.approx(2.0)


def test_pricing_snapshot_has_source_date_unit_and_cache_price():
    pricing = MODEL_PRICING_USD_PER_MILLION_TOKENS["openai/gpt-4.1-mini"]
    assert pricing["input"] == 0.40
    assert pricing["output"] == 1.60
    assert pricing["cache_read"] == 0.10
    assert pricing["unit"] == "USD per 1,000,000 tokens"
    assert pricing["source"].startswith("https://openrouter.ai/")
    assert pricing["as_of"] == "2026-09-24"
    assert DEFAULT_OPENROUTER_MODEL == "openai/gpt-4.1-mini"


def test_official_snapshot_estimation_formula():
    assert estimate_cost_usd("openai/gpt-4.1-mini", 500_000, 250_000) == pytest.approx(0.60)


def test_unknown_model_or_missing_tokens_are_not_estimated():
    assert estimate_cost_usd("unknown/model", 100, 100) is None
    assert estimate_cost_usd("openai/gpt-4.1-mini", None, 100) is None
    assert estimate_cost_usd("openai/gpt-4.1-mini", 100, None) is None


@pytest.mark.parametrize("bad_token", [-1, True, 1.5, "10"])
def test_invalid_tokens_are_rejected_by_estimator(bad_token):
    assert estimate_cost_usd("openai/gpt-4.1-mini", bad_token, 10) is None
    assert estimate_cost_usd("openai/gpt-4.1-mini", 10, bad_token) is None


@pytest.mark.parametrize("bad_cost", [-0.01, True, "0.01"])
def test_invalid_api_cost_is_rejected(monkeypatch, facts, bad_cost):
    payload = {
        "id": "gen-safe", "model": "openai/gpt-4.1-mini",
        "choices": [{"message": {"content": json.dumps(valid_output(facts), ensure_ascii=False)}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "cost": bad_cost},
    }
    assert mocked_generation(monkeypatch, facts, payload).exact_cost_usd is None


def test_missing_usage_does_not_fail_explanation(monkeypatch, facts):
    payload = {
        "id": "gen-no-usage", "model": "openai/gpt-4.1-mini",
        "choices": [{"message": {"content": json.dumps(valid_output(facts), ensure_ascii=False)}}],
    }
    result = mocked_generation(monkeypatch, facts, payload)
    assert result.input_tokens is None and result.output_tokens is None and result.total_tokens is None
    assert result.exact_cost_usd is None and result.estimated_cost_usd is None


def test_invalid_or_missing_token_fields_do_not_fail_explanation(monkeypatch, facts):
    payload = {
        "model": "openai/gpt-4.1-mini",
        "choices": [{"message": {"content": json.dumps(valid_output(facts), ensure_ascii=False)}}],
        "usage": {"prompt_tokens": -1, "completion_tokens": True, "total_tokens": "bad"},
    }
    result = mocked_generation(monkeypatch, facts, payload)
    assert result.input_tokens is None and result.output_tokens is None and result.total_tokens is None
    assert result.estimated_cost_usd is None


def test_exact_cost_display_takes_priority_over_estimate():
    result = LLMResult({}, "", "model", 1, 1, 2, 0.1, exact_cost_usd=0.25, estimated_cost_usd=0.10)
    label, value, note = displayed_cost(result)
    assert label.startswith("Exact API Cost")
    assert value == 0.25
    assert "API response" in note


def test_estimated_cost_display_is_explicitly_not_final_bill():
    result = LLMResult({}, "", "model", 1, 1, 2, 0.1, estimated_cost_usd=0.10)
    label, value, note = displayed_cost(result)
    assert label.startswith("Estimated Cost")
    assert value == 0.10
    assert "not a final bill" in note


def test_no_cost_is_displayed_as_unavailable_not_zero():
    result = LLMResult({}, "", "model", None, None, None, 0.1)
    assert displayed_cost(result) is None


def test_unsupported_structured_output_fails_without_downgrade(monkeypatch, facts):
    class FakeResponse:
        status_code = 400
        text = "safe test response"
        def json(self):
            return {"error": {"code": 400, "message": "No endpoints found that support structured outputs"}}
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-real")
    monkeypatch.setattr("src.llm_client.load_dotenv", lambda: False)
    monkeypatch.setattr("src.llm_client.requests.post", lambda *a, **k: FakeResponse())
    with pytest.raises(LLMConfigurationError) as caught:
        generate_explanation(facts)
    assert caught.value.status_code == 400
    assert caught.value.category == "structured_outputs_unsupported"


def test_incompatible_schema_http_error_is_diagnosed_separately(monkeypatch, facts):
    class FakeResponse:
        status_code = 400
        text = "safe test response"
        def json(self):
            return {"error": {"code": 400, "message": "Invalid schema: unsupported keyword minLength"}}
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-real")
    monkeypatch.setattr("src.llm_client.load_dotenv", lambda: False)
    monkeypatch.setattr("src.llm_client.requests.post", lambda *a, **k: FakeResponse())
    with pytest.raises(LLMConfigurationError, match="JSON Schema") as caught:
        generate_explanation(facts)
    assert caught.value.status_code == 400
    assert caught.value.category == "schema_incompatible"


@pytest.mark.parametrize(
    ("status", "message", "category"),
    [(401, "Invalid API key", "authentication"), (402, "Insufficient balance", "balance")],
)
def test_authentication_and_balance_errors_are_safe(monkeypatch, facts, status, message, category):
    class FakeResponse:
        status_code = status
        text = "safe test response"
        def json(self):
            return {"error": {"code": status, "message": message}}
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-real")
    monkeypatch.setattr("src.llm_client.load_dotenv", lambda: False)
    monkeypatch.setattr("src.llm_client.requests.post", lambda *a, **k: FakeResponse())
    with pytest.raises(LLMConfigurationError) as caught:
        generate_explanation(facts)
    assert caught.value.status_code == status
    assert caught.value.category == category
    assert "test-key-not-real" not in str(caught.value)


def test_http_timeout_is_english_and_isolated(monkeypatch, facts):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-real")
    monkeypatch.setattr("src.llm_client.load_dotenv", lambda: False)
    monkeypatch.setattr("src.llm_client.requests.post", lambda *a, **k: (_ for _ in ()).throw(requests.Timeout()))
    with pytest.raises(LLMRequestError, match="Python"):
        generate_explanation(facts)


def test_paid_response_metadata_survives_local_validation_failure(monkeypatch, facts):
    payload = {
        "id": "gen-paid-invalid", "model": "openai/gpt-4.1-mini",
        "choices": [{"message": {"content": "not-json"}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120, "cost": 0.001},
    }
    with pytest.raises(LLMRequestError) as caught:
        mocked_generation(monkeypatch, facts, payload)
    metadata = caught.value.response_metadata
    assert metadata["generation_id"] == "gen-paid-invalid"
    assert metadata["total_tokens"] == 120
    assert metadata["exact_cost_usd"] == 0.001
    assert metadata["raw_output"] == "not-json"


def test_cache_key_includes_source_date_row_model_prompt_and_schema():
    source = upload_signature(b"file", TEST_DATE)
    base = llm_cache_key(source, "PO|10|MAT|P1", "model-a", PROMPT_VERSION, SCHEMA_VERSION)
    variants = [
        llm_cache_key(upload_signature(b"other", TEST_DATE), "PO|10|MAT|P1", "model-a", PROMPT_VERSION, SCHEMA_VERSION),
        llm_cache_key(upload_signature(b"file", date(2026, 9, 26)), "PO|10|MAT|P1", "model-a", PROMPT_VERSION, SCHEMA_VERSION),
        llm_cache_key(source, "PO|20|MAT|P1", "model-a", PROMPT_VERSION, SCHEMA_VERSION),
        llm_cache_key(source, "PO|10|MAT|P1", "model-b", PROMPT_VERSION, SCHEMA_VERSION),
        llm_cache_key(source, "PO|10|MAT|P1", "model-a", "new-prompt", SCHEMA_VERSION),
        llm_cache_key(source, "PO|10|MAT|P1", "model-a", PROMPT_VERSION, "new-schema"),
    ]
    assert all(value != base for value in variants)


def test_ui_previews_only_structured_row_and_privacy_notice(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr("src.llm_client.load_dotenv", lambda: False)
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
    app.date_input[0].set_value(TEST_DATE).run()
    sample = ROOT / "test_data" / "sample_workbook.xlsx"
    app.file_uploader[0].upload(sample.name, sample.read_bytes(), XLSX_MIME).run()
    next(b for b in app.button if b.label.startswith("Validate Workbook")).click().run()
    next(b for b in app.button if b.label == "Run Analysis").click().run()
    assert any(item.label == "OpenRouter API Key" for item in app.text_input)
    assert any("OpenRouter API Key" in item.value for item in app.info)
    assert any(item.label.startswith("Preview of Data Eligible to Be Sent to AI") for item in app.expander)
    preview = json.dumps(app.json[0].value, ensure_ascii=False)
    assert "Shortage_Quantity" in preview
    assert "OPENROUTER_API_KEY" not in preview and "Orders" not in preview


def test_ui_reuses_successful_result_without_duplicate_api_call(monkeypatch, facts):
    calls = []
    fake_result = LLMResult(valid_output(facts), "{}", "test/model", 10, 10, 20, 0.1)
    monkeypatch.setattr("src.llm_client.configured_model", lambda: "test/model")
    monkeypatch.setattr(
        "src.llm_client.generate_explanation",
        lambda sent, api_key=None: calls.append((sent, api_key)) or fake_result,
    )
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
    app.date_input[0].set_value(TEST_DATE).run()
    sample = ROOT / "test_data" / "sample_workbook.xlsx"
    app.file_uploader[0].upload(sample.name, sample.read_bytes(), XLSX_MIME).run()
    next(b for b in app.button if b.label.startswith("Validate Workbook")).click().run()
    next(b for b in app.button if b.label == "Run Analysis").click().run()
    next(item for item in app.text_input if item.label == "OpenRouter API Key").set_value("test-key-not-real").run()
    next(b for b in app.button if b.label.startswith("Generate Advisory Action Plan")).click().run()
    assert len(calls) == 1
    assert calls[0][1] == "test-key-not-real"
    assert not any(b.label.startswith("Generate Advisory Action Plan") for b in app.button)
    assert len(calls) == 1
    assert any("no duplicate API call" in item.value for item in app.success)
    rendered_html = "\n".join(item.value for item in app.markdown)
    assert 'class="ai-summary"' in rendered_html
    assert 'class="action-number"' in rendered_html
    assert "Human review required" in rendered_html


def test_ai_order_selection_is_independent_of_overview_filters(monkeypatch):
    calls = []
    fake_result = LLMResult({
        "priority_summary": "Review required.",
        "explanation": "The selected order has verified exceptions.",
        "exception_reviews": [],
        "recommended_actions": [{"action_type": "Review", "action": "Review the selected order."}],
        "missing_information_codes": [],
    }, "{}", "test/model", 10, 10, 20, 0.1)
    monkeypatch.setattr("src.llm_client.configured_model", lambda: "test/model")
    monkeypatch.setattr(
        "src.llm_client.generate_explanation",
        lambda sent, api_key=None: calls.append((sent, api_key)) or fake_result,
    )
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=20).run()
    app.date_input[0].set_value(TEST_DATE).run()
    sample = ROOT / "data" / "expanded_scenarios" / "generated" / "large" / "L04.xlsx"
    app.file_uploader[0].upload(sample.name, sample.read_bytes(), XLSX_MIME).run()
    next(b for b in app.button if b.label.startswith("Validate Workbook")).click().run()
    next(b for b in app.button if b.label == "Run Analysis").click().run()

    order_selector = next(item for item in app.selectbox if item.label == "Selected order line")
    order_selector.select(order_selector.options[-1]).run(timeout=20)
    selected_before_filter = app.session_state["selected_order"]

    priority_filter = next(item for item in app.selectbox if item.label == "Issue Priority")
    priority_filter.select("Medium").run(timeout=20)

    filtered_selector = next(item for item in app.selectbox if item.label == "Selected order line")
    assert filtered_selector.value in filtered_selector.options
    assert app.session_state["selected_order"] == tuple(
        part.strip() for part in filtered_selector.value.split("/", 1)
    )
    assert app.session_state["selected_order"] == selected_before_filter

    next(item for item in app.text_input if item.label == "OpenRouter API Key").set_value("test-key-not-real").run(timeout=20)
    next(b for b in app.button if b.label.startswith("Generate Advisory Action Plan")).click().run(timeout=20)
    assert len(calls) == 1
    assert any("no duplicate API call" in item.value for item in app.success)


def test_file_or_date_change_clears_session_ai_cache(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
    app.date_input[0].set_value(TEST_DATE).run()
    sample = ROOT / "test_data" / "sample_workbook.xlsx"
    app.file_uploader[0].upload(sample.name, sample.read_bytes(), XLSX_MIME).run()
    app.session_state["llm_results"] = {"old": "result"}
    app.date_input[0].set_value(date(2026, 9, 26)).run()
    with pytest.raises(KeyError):
        _ = app.session_state["llm_results"]


def test_live_smoke_script_defaults_to_no_call():
    completed = subprocess.run(
        [sys.executable, str(ROOT / "tests" / "run_live_llm_smoke_test.py")],
        cwd=ROOT, capture_output=True, text=True, timeout=10, check=False,
    )
    assert completed.returncode == 0
    assert "No live API call" in completed.stdout


def test_versions_are_explicit_and_stable():
    assert PROMPT_VERSION.startswith("phase6-")
    assert SCHEMA_VERSION.startswith("phase6-")
