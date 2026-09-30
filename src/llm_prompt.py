"""Restricted LLM facts, prompt, and schema."""

import json
from datetime import date
from typing import Any, Mapping

import pandas as pd

PROMPT_VERSION = "phase6-prompt-v15-python-canonical-actions"
SCHEMA_VERSION = "phase6-schema-v10-overdue-schedule-impact"

ALLOWED_ACTION_TYPES = [
    "Check whether an incoming delivery can be expedited",
    "Escalate to procurement",
    "Escalate to production planning",
    "Request missing data",
    "Take no immediate action when supply is sufficient",
]

EVIDENCE_FIELDS = [
    "Analysis_Date", "Production_Order_ID", "Production_Order_Item",
    "Source_Sales_Order_ID", "Source_Sales_Order_Item", "Product_ID",
    "Material_ID", "Plant", "Material_Need_Date", "Required_Quantity",
    "Quantity_Unit", "Unrestricted_Inventory", "Safety_Stock", "Usable_Inventory",
    "Eligible_Incoming_Quantity", "Late_Incoming_Quantity", "Overdue_Incoming_Quantity",
    "Total_Available", "Inventory_Allocated", "Incoming_PO_Allocated",
    "Shortage_Quantity", "Next_Receipt_Date", "Python_Priority",
    "Priority_Rule_ID", "Calculation_Explanation", "Requested_Delivery_Date",
    "Planned_Start_Date", "Planned_End_Date", "Days_After_Requested_Delivery",
    "Inventory_Available_Before_Allocation", "Impact_Class", "Direct_Order_Impact",
    "Supply_Relationship", "Directly_Pegged_To_Order",
]

QUANTITY_EVIDENCE_FIELDS = {
    "Required_Quantity", "Unrestricted_Inventory", "Safety_Stock", "Usable_Inventory",
    "Eligible_Incoming_Quantity", "Late_Incoming_Quantity", "Overdue_Incoming_Quantity",
    "Total_Available", "Inventory_Available_Before_Allocation", "Inventory_Allocated", "Incoming_PO_Allocated", "Shortage_Quantity",
}

STRING_EVIDENCE_FIELDS = {
    "Production_Order_ID", "Production_Order_Item", "Source_Sales_Order_ID",
    "Source_Sales_Order_Item", "Product_ID", "Material_ID", "Plant",
    "Quantity_Unit", "Python_Priority", "Priority_Rule_ID", "Calculation_Explanation",
    "Impact_Class", "Supply_Relationship",
}

DATE_EVIDENCE_FIELDS = {
    "Analysis_Date", "Material_Need_Date", "Next_Receipt_Date",
    "Requested_Delivery_Date", "Planned_Start_Date", "Planned_End_Date",
}

MISSING_INFORMATION = {
    "SUPPLIER_CONFIRMATION": "Supplier confirmation",
    "EXPEDITING_FEASIBILITY": "Expediting feasibility",
    "EXPEDITING_COST_APPROVAL": "Expediting cost approval",
    "ALTERNATIVE_MATERIAL_APPROVAL": "Alternative material approval",
    "RESCHEDULING_CONSTRAINTS": "Rescheduling constraints",
    "RESCHEDULING_APPROVAL": "Rescheduling approval",
    "CROSS_ORDER_SUPPLY_DEPENDENCIES": "Cross-order supply dependencies",
    "SOURCING_OR_PURCHASE_ORDER_STATUS": "Sourcing or purchase-order status",
    "SUPPLY_LEAD_TIME": "Supply lead time",
    "PRODUCTION_SCHEDULE_CONSTRAINTS": "Production schedule constraints",
}
MISSING_INFORMATION_CODES = list(MISSING_INFORMATION)

FIXED_HUMAN_REVIEW_NOTICE = (
    "AI-generated content is advisory. All actions require planner review. This system has not executed any action "
    "and cannot modify SAP or create purchase orders."
)


def _json_value(field: str, value: Any) -> Any:
    if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
        return None
    if field in DATE_EVIDENCE_FIELDS:
        if isinstance(value, (date, pd.Timestamp)):
            return value.strftime("%Y-%m-%d")
        return str(value)
    if field in STRING_EVIDENCE_FIELDS:
        return str(value)
    if field in QUANTITY_EVIDENCE_FIELDS:
        return float(value)
    if isinstance(value, (date, pd.Timestamp)):
        return value.strftime("%Y-%m-%d")
    if hasattr(value, "item"):
        return value.item()
    return value


def build_structured_input(row: Mapping[str, Any]) -> dict[str, Any]:
    """Select one calculated row only; never send the workbook."""
    normalized: dict[str, Any] = {}
    for target in EVIDENCE_FIELDS:
        source = "Priority" if target == "Python_Priority" else target
        normalized[target] = _json_value(target, row.get(source))
    return normalized


def build_output_schema() -> dict[str, Any]:
    """Return the strict output schema used remotely and locally."""
    evidence = {
        "type": "object", "additionalProperties": False,
        "properties": {
            "exception_id": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "field": {"type": "string", "enum": EVIDENCE_FIELDS},
            "value": {"anyOf": [{"type": "string"}, {"type": "number"}, {"type": "null"}]},
            "unit": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
        "required": ["exception_id", "field", "value", "unit"],
    }
    action = {
        "type": "object", "additionalProperties": False,
        "properties": {
            "action_type": {"type": "string", "enum": ALLOWED_ACTION_TYPES},
            "action": {"type": "string"},
            "evidence": {"type": "array", "items": evidence},
            "requires_human_approval": {"type": "boolean", "enum": [True]},
            "execution_status": {"type": "string", "enum": ["NOT_EXECUTED"]},
        },
        "required": ["action_type", "action", "evidence", "requires_human_approval", "execution_status"],
    }
    exception_review = {
        "type": "object", "additionalProperties": False,
        "properties": {
            "exception_id": {"type": "string"},
            "exception_type": {"type": "string"},
            "material_id": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "priority": {"type": "string", "enum": ["Critical", "High", "Medium", "Low"]},
            "material_need_date": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "quantity_unit": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "shortage_quantity": {"anyOf": [{"type": "number"}, {"type": "null"}]},
            "late_incoming_quantity": {"anyOf": [{"type": "number"}, {"type": "null"}]},
            "overdue_incoming_quantity": {"anyOf": [{"type": "number"}, {"type": "null"}]},
            "next_receipt_date": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "requested_delivery_date": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "planned_start_date": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "planned_end_date": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "days_after_requested_delivery": {"anyOf": [{"type": "number"}, {"type": "null"}]},
            "impact_class": {"type": "string", "enum": ["BLOCKING", "AT_RISK", "MONITOR"]},
            "direct_order_impact": {"type": "boolean"},
            "supply_relationship": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "directly_pegged_to_order": {"anyOf": [{"type": "boolean"}, {"type": "null"}]},
            "finding": {"type": "string"},
            "recommended_review": {"type": "string"},
            "requires_human_approval": {"type": "boolean", "enum": [True]},
            "execution_status": {"type": "string", "enum": ["NOT_EXECUTED"]},
        },
        "required": [
            "exception_id", "exception_type", "material_id", "priority",
            "material_need_date", "quantity_unit", "shortage_quantity", "late_incoming_quantity",
            "overdue_incoming_quantity", "next_receipt_date", "requested_delivery_date",
            "planned_start_date", "planned_end_date", "days_after_requested_delivery",
            "impact_class", "direct_order_impact", "supply_relationship", "directly_pegged_to_order",
            "finding", "recommended_review",
            "requires_human_approval", "execution_status",
        ],
    }
    return {
        "type": "object", "additionalProperties": False,
        "properties": {
            "priority_summary": {"type": "string"},
            "explanation": {"type": "string"},
            "python_priority": {"type": "string"},
            "priority_rule_id": {"type": "string"},
            "exception_reviews": {"type": "array", "items": exception_review},
            "recommended_actions": {"type": "array", "items": action},
            "missing_information_codes": {
                "type": "array",
                "items": {"type": "string", "enum": MISSING_INFORMATION_CODES},
            },
        },
        "required": [
            "priority_summary", "explanation", "python_priority", "priority_rule_id",
            "exception_reviews", "recommended_actions", "missing_information_codes",
        ],
    }


def build_response_format() -> dict[str, Any]:
    return {"type": "json_schema", "json_schema": {"name": "shortage_advisory", "strict": True, "schema": build_output_schema()}}


SYSTEM_PROMPT = """You explain an order-scoped deterministic production-planning fact package for human review.

Python facts are the sole source of truth. Never recalculate or alter a number, date, identifier, status, shortage, priority, or rule ID.
Never invent suppliers, prices, lead times, transport modes, customer importance, alternative materials, approvals, or completed actions.
All narrative text must be in English only.

The top-level material fields contain one representative calculated material row. For a non-material Primary_Exception, use Primary_Exception and its exception-scoped facts for the explanation rather than treating the representative material row as the cause.
Python_Priority and Priority_Rule_ID are the deterministic priority and rule for Primary_Exception.
Verified_Exceptions is the authoritative bounded list of detected exceptions for the selected order.
Order_Has_Material_Shortage and Order_Has_Late_Or_Overdue_Supply summarize the entire selected order, not only the top-level material row.
Explain Primary_Exception first. Do not describe a different material as the reason for the displayed exception.
Do not say that the selected order has no exceptions when Order_Exception_Count is positive.
Do not infer that the entire order is supply-sufficient merely because the top-level Shortage_Quantity is zero; use Order_Has_Material_Shortage for that conclusion.
For backward-compatible single-row calls where the order-scoped fields are absent, treat the top-level calculated row as the entire available scope.

Complete exception coverage policy:

1. Return exactly one exception_reviews item for every item in Verified_Exceptions, preserving the same order. Do not omit, merge, duplicate, or invent exceptions.
2. Copy every structured exception-review field exactly from that Verified_Exceptions item, including overdue quantity, schedule dates, impact class, direct-order impact, supply relationship and pegging status. Use null when the deterministic field is null.
3. In finding, explain what is exceptional and whether the verified shortage is zero or positive. Do not describe a late delivery as causing a shortage when Shortage_Quantity is zero.
   Do not use subjective severity words such as "large", "significant", or "substantial" unless a deterministic field explicitly supplies that classification.
   A null field on one exception means only that the field is not applicable to that exception; never generalize it into a claim that the order has no such condition.
4. In recommended_review, state only a human review step supported by that exception. Never claim the review or any operational action has occurred.
5. Set requires_human_approval to true and execution_status to NOT_EXECUTED for every exception review.
6. If Verified_Exceptions is absent, return an empty exception_reviews array.
7. If payload_truncated is true, acknowledge the exact nonzero additional_* counts supplied by Python and identify whether exceptions, affected materials, or PO lines were omitted. Never claim the displayed list is exhaustive.
8. For PRODUCTION_BACKLOG, explain the deterministic cause using Planned_End_Date, Analysis_Date, Remaining_Quantity, and Production_Order_Status when present. Do not use zero Shortage_Quantity or null Late_Incoming_Quantity as the explanation for a backlog.
9. Keep priority_summary and explanation concise. Use one concise sentence for each finding and each recommended_review so the complete bounded exception list fits within the output limit.
10. Never call a receipt delayed unless the facts contain an original confirmed date and a later revised date. With the current fields, say only that the expected receipt is after the need date or is overdue as of Analysis_Date.
11. Supply_Relationship MATERIAL_PLANT_POOL is not direct pegging. Never say that a related PO is committed to or specifically supplies the selected sales or production order when Directly_Pegged_To_Order is false.
12. When Usable_Inventory is positive but Inventory_Available_Before_Allocation is zero, say that no remaining usable inventory was available at this demand's allocation point. Never say that no usable inventory exists.

Use only schema enums.
Every action is advisory, requires human approval, and has execution_status NOT_EXECUTED.
Never claim that an action has occurred.
Python will replace all copied exception facts, action types, evidence values, evidence units, and missing-information codes with deterministic values before display. Focus on accurate, concise narrative text; do not reinterpret those facts or action conditions.

Conservative action policy:

1. If Order_Has_Material_Shortage is true, never claim that supply is sufficient for the selected order.
2. If Primary_Exception_Type is MATERIAL_SHORTAGE, "Escalate to procurement" is the default supported action. Describe it only as escalation for human investigation of supply options. Do not claim that purchasing or replenishment will occur.
3. Recommend "Check whether an incoming delivery can be expedited" only when Shortage_Quantity is positive and Late_Incoming_Quantity or Overdue_Incoming_Quantity is greater than zero.
4. If Primary_Exception_Type is LATE_INCOMING_SUPPLY or OVERDUE_INCOMING_SUPPLY and Shortage_Quantity is zero, clearly state both facts: the selected material demand is currently covered, but a shared material-plant supply timing exception still exists. Prefer "Request missing data" for the Python-supplied Required_Missing_Information_Codes; do not recommend expediting solely for this selected order.
   For every verified late- or overdue-supply exception where Inventory_Allocated is at least Required_Quantity, explicitly state in that exception's finding that inventory covers the full requirement or demand. Recommend checking whether the supply-pool timing signal is relevant to other orders, but do not claim that another order is affected without deterministic cross-order evidence.
5. Recommend "Take no immediate action when supply is sufficient" only when Verified_Exceptions is empty. A production backlog or schedule exception still requires production-planning review even when material shortage is zero.
6. Eligible_Incoming_Quantity is already timely and does not support expediting.
7. Do not recommend production-order rescheduling, cross-order material allocation, or alternative materials because this payload does not contain enough facts to support those actions.
8. Both exception_reviews and recommended_actions must cover every verified exception. Every Exception_ID must appear in at least one recommended action's exception-scoped evidence. Recommended actions may consolidate identical review steps across exceptions, but the action text must identify every affected material or production order included in that consolidated action.
9. Prefer one fully supported action when it can cover all included verified exceptions; otherwise use the smallest fully supported set that achieves complete coverage.
10. Cover MATERIAL_SHORTAGE with "Escalate to procurement"; LATE_INCOMING_SUPPLY or OVERDUE_INCOMING_SUPPLY with "Request missing data"; and PRODUCTION_BACKLOG, UNSCHEDULED_ORDER, PLANNED_COMPLETION_AFTER_REQUESTED_DELIVERY, or ZERO_SCHEDULE_BUFFER with "Escalate to production planning". Do not let an action for Primary_Exception stand in for a different exception type.
11. Copy Required_Missing_Information_Codes exactly into missing_information_codes. Do not require supplier confirmation when no related PO exists; use sourcing or purchase-order status and supply lead time instead.

Evidence policy:

1. Include only the minimum evidence needed to support each action.
2. Never copy the complete input row into Evidence.
3. Never use Calculation_Explanation as Evidence.
4. Every evidence item must include exception_id. Set it to the matching Exception_ID when citing a Verified_Exceptions item. Set it to null only when citing a top-level field for Primary_Exception.
5. When exception_id is not null, copy field and value from that exact Verified_Exceptions item. Never combine the field from one exception with the value from another.
6. For "Take no immediate action when supply is sufficient", cite Shortage_Quantity and optionally one supply field.
7. For "Escalate to procurement", cite Shortage_Quantity and optionally Material_ID or Python_Priority.
8. For expediting, cite at least one positive Late_Incoming_Quantity or Overdue_Incoming_Quantity and optionally Shortage_Quantity.
9. For "Request missing data" about late incoming supply, use exception-scoped evidence for every affected exception included in the consolidated action. Cite Late_Incoming_Quantity or Next_Receipt_Date from each one.
10. Copy every cited value exactly from the selected scope, including its JSON type.
11. Identifier and item fields are strings, even when they contain only digits.
12. For every material-quantity evidence item, including a zero quantity, set unit exactly to the selected scope's Quantity_Unit.
13. For every non-material-quantity evidence item, including Days_After_Requested_Delivery, set unit to null.

Use only the fixed missing-information codes.
Return only schema-compliant JSON with no Markdown fences or additional text."""


def build_messages(structured_input: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "Explain only these Python-calculated facts:\n" + json.dumps(structured_input, ensure_ascii=False, indent=2)},
    ]
