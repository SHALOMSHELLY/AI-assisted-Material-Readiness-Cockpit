"""Minimal OpenRouter client with safe failure handling."""

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any

import requests
from dotenv import load_dotenv

from config.settings import (
    DEFAULT_OPENROUTER_MODEL,
    LLM_MAX_OUTPUT_TOKENS,
    LLM_REQUEST_TIMEOUT_SECONDS,
    MODEL_PRICING_USD_PER_MILLION_TOKENS,
    OPENROUTER_API_URL,
)
from src.llm_prompt import (
    ALLOWED_ACTION_TYPES,
    EVIDENCE_FIELDS,
    MISSING_INFORMATION_CODES,
    QUANTITY_EVIDENCE_FIELDS,
    build_messages,
    build_response_format,
)


class LLMConfigurationError(Exception):
    """The API configuration is missing or incompatible."""

    def __init__(self, message: str, status_code: int | None = None, category: str = "configuration"):
        super().__init__(message)
        self.status_code = status_code
        self.category = category


class LLMRequestError(Exception):
    """The remote request failed or returned invalid output."""

    def __init__(self, message: str, status_code: int | None = None, category: str = "request",
                 response_metadata: dict[str, Any] | None = None):
        if category == "request":
            lowered = message.lower()
            local_safety_markers = (
                "does not match python facts", "disallowed action", "human approval",
                "action was executed", "execution already occurred", "disallowed field",
                "positive incoming supply", "positive incoming-supply field",
                "no-immediate-action", "procurement escalation requires",
                "lacks the facts needed", "cannot be recommended for expediting",
                "subjective severity", "supply-sufficient", "python",
            )
            structured_markers = (
                "output is empty", "not valid json", "fixed structure", "empty required text",
                "must be a list", "must include evidence", "unknown code", "must be unique",
                "json", "evidence", "exception_reviews", "exception review",
            )
            if any(marker in lowered for marker in local_safety_markers):
                category = "local_safety_validation"
            elif any(marker in lowered for marker in structured_markers):
                category = "structured_validation"
        super().__init__(message)
        self.status_code = status_code
        self.category = category
        self.response_metadata = response_metadata


EXECUTION_CLAIM_MARKERS = (
    "automatically created", "already created", "has been created", "was created",
    "already contacted", "has been contacted", "was contacted", "already modified",
)

UNSUPPORTED_SEVERITY_PATTERN = re.compile(
    r"\b(?:large|significant|substantial)\s+(?:quantity|amount|shortage|supply|impact|risk)\b",
    re.IGNORECASE,
)
UNSUPPORTED_DELAY_CLAIM_PATTERN = re.compile(
    r"\b(?:supplier\s+deliver(?:y|ies)\s+(?:is|are|was|were)\s+delayed|supplier\s+delay|"
    r"delayed\s+(?:receipt|incoming\s+supply|supply)|"
    r"(?:receipt|incoming\s+supply|supply)\s+(?:is|was|appears)\s+delayed|was\s+postponed)\b",
    re.IGNORECASE,
)

ORDER_SUPPLY_SUFFICIENT_PATTERNS = (
    re.compile(r"\b(?:selected\s+)?order\s+(?:overall\s+)?has\s+no\s+(?:material\s+)?shortages?\b", re.IGNORECASE),
    re.compile(r"\bno\s+material\s+shortages?\s+(?:exist|exists|overall)\b", re.IGNORECASE),
    re.compile(r"\bsupply\s+is\s+sufficient\s+for\s+the\s+(?:selected\s+)?order\b", re.IGNORECASE),
)

HAN_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

EXPEDITE_ACTION_TYPE = "Check whether an incoming delivery can be expedited"
REQUEST_MISSING_DATA_ACTION_TYPE = "Request missing data"
EXPEDITE_SUPPORT_FIELDS = {
    "Late_Incoming_Quantity",
    "Overdue_Incoming_Quantity",
}

EXCEPTION_REVIEW_FACT_FIELDS = {
    "exception_id": "Exception_ID",
    "exception_type": "Exception_Type",
    "material_id": "Material_ID",
    "priority": "Priority",
    "material_need_date": "Material_Need_Date",
    "quantity_unit": "Quantity_Unit",
    "shortage_quantity": "Shortage_Quantity",
    "late_incoming_quantity": "Late_Incoming_Quantity",
    "overdue_incoming_quantity": "Overdue_Incoming_Quantity",
    "next_receipt_date": "Next_Receipt_Date",
    "requested_delivery_date": "Requested_Delivery_Date",
    "planned_start_date": "Planned_Start_Date",
    "planned_end_date": "Planned_End_Date",
    "days_after_requested_delivery": "Days_After_Requested_Delivery",
    "impact_class": "Impact_Class",
    "direct_order_impact": "Direct_Order_Impact",
    "supply_relationship": "Supply_Relationship",
    "directly_pegged_to_order": "Directly_Pegged_To_Order",
}

PRODUCTION_PLANNING_EXCEPTION_TYPES = {
    "PRODUCTION_BACKLOG", "UNSCHEDULED_ORDER",
    "PLANNED_COMPLETION_AFTER_REQUESTED_DELIVERY", "ZERO_SCHEDULE_BUFFER",
}


@dataclass(frozen=True)
class LLMResult:
    """Hold one explanation and its call metadata."""

    parsed_output: dict[str, Any]
    raw_output: str
    model: str
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    response_time_seconds: float
    generation_id: str | None = None
    exact_cost_usd: float | None = None
    estimated_cost_usd: float | None = None
    pricing_source: str | None = None
    pricing_as_of: str | None = None


def configured_api_key() -> str:
    """Read a local environment key without accepting the placeholder."""

    load_dotenv()
    value = os.getenv("OPENROUTER_API_KEY", "").strip()
    return "" if not value or value == "your_api_key_here" else value


def configured_model() -> str:
    """Allow a local environment override for the model."""

    return os.getenv("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL).strip() or DEFAULT_OPENROUTER_MODEL


def _same_value(actual: Any, expected: Any) -> bool:
    if isinstance(actual, bool) or isinstance(expected, bool):
        return type(actual) is type(expected) and actual == expected
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return float(actual) == float(expected)
    return type(actual) is type(expected) and actual == expected


def _nonnegative_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _nonnegative_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return float(value)


def _generation_id(value: Any, api_key: str) -> str | None:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", value):
        return None
    if api_key and api_key in value:
        return None
    return value


def estimate_cost_usd(model: str, input_tokens: Any, output_tokens: Any) -> float | None:
    """Estimate cost from the recorded list-price snapshot."""

    pricing = MODEL_PRICING_USD_PER_MILLION_TOKENS.get(model)
    input_count = _nonnegative_int(input_tokens)
    output_count = _nonnegative_int(output_tokens)
    if pricing is None or input_count is None or output_count is None:
        return None
    return input_count / 1_000_000 * pricing["input"] + output_count / 1_000_000 * pricing["output"]


def displayed_cost(result: LLMResult) -> tuple[str, float, str] | None:
    """Prefer exact provider cost to a local estimate."""

    if result.exact_cost_usd is not None:
        return "Exact API Cost", result.exact_cost_usd, "API response"
    if result.estimated_cost_usd is not None:
        return (
            "Estimated Cost", result.estimated_cost_usd,
            "Estimate from the recorded pricing snapshot; not a final bill.",
        )
    return None


def extract_response_metadata(payload: dict[str, Any], requested_model: str, api_key: str,
                              response_time_seconds: float, raw_output: str) -> dict[str, Any]:
    """Extract paid-call metadata before local output validation."""

    usage = payload.get("usage", {})
    if not isinstance(usage, dict):
        usage = {}
    input_tokens = _nonnegative_int(usage.get("prompt_tokens"))
    output_tokens = _nonnegative_int(usage.get("completion_tokens"))
    total_tokens = _nonnegative_int(usage.get("total_tokens"))
    actual_model = payload.get("model") if isinstance(payload.get("model"), str) else requested_model
    pricing = MODEL_PRICING_USD_PER_MILLION_TOKENS.get(actual_model)
    return {
        "model": actual_model,
        "generation_id": _generation_id(payload.get("id"), api_key),
        "input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": total_tokens,
        "response_time_seconds": response_time_seconds,
        "exact_cost_usd": _nonnegative_number(usage.get("cost")),
        "estimated_cost_usd": estimate_cost_usd(actual_model, input_tokens, output_tokens),
        "pricing_source": pricing["source"] if pricing else None,
        "pricing_as_of": pricing["as_of"] if pricing else None,
        "raw_output": raw_output,
    }


def validate_action_support(action: dict[str, Any], structured_input: dict[str, Any]) -> None:
    """Reject actions that the deterministic order-scoped facts cannot support."""

    action_type = action.get("action_type")
    shortage = structured_input.get("Shortage_Quantity")
    has_shortage = (
        isinstance(shortage, (int, float))
        and not isinstance(shortage, bool)
        and shortage > 0
    )
    order_has_shortage = structured_input.get("Order_Has_Material_Shortage")
    if not isinstance(order_has_shortage, bool):
        order_has_shortage = has_shortage
    if action_type == "Take no immediate action when supply is sufficient" and order_has_shortage:
        raise LLMRequestError(
            "No-immediate-action cannot be recommended when the selected order has a material shortage."
        )
    if action_type == "Take no immediate action when supply is sufficient" and structured_input.get("Verified_Exceptions"):
        raise LLMRequestError(
            "No-immediate-action cannot be recommended while verified exceptions require review."
        )
    if action_type == "Escalate to procurement" and not order_has_shortage:
        raise LLMRequestError(
            "Procurement escalation requires a positive verified material shortage."
        )
    evidence_exception_ids = {
        item.get("exception_id") for item in action.get("evidence", [])
        if isinstance(item, dict) and isinstance(item.get("exception_id"), str)
    }
    verified = structured_input.get("Verified_Exceptions", [])
    covers_late_exception = any(
        isinstance(item, dict)
        and item.get("Exception_ID") in evidence_exception_ids
        and item.get("Exception_Type") in {"LATE_INCOMING_SUPPLY", "OVERDUE_INCOMING_SUPPLY"}
        for item in verified if isinstance(verified, list)
    )
    if not evidence_exception_ids:
        covers_late_exception = structured_input.get("Primary_Exception_Type") == "LATE_INCOMING_SUPPLY"
    if action_type == REQUEST_MISSING_DATA_ACTION_TYPE and covers_late_exception:
        cited_fields = {
            item.get("field") for item in action.get("evidence", []) if isinstance(item, dict)
        }
        if not cited_fields.intersection({
            "Late_Incoming_Quantity", "Overdue_Incoming_Quantity",
            "Next_Receipt_Date",
        }):
            raise LLMRequestError(
                "Request-missing-data advice for a late incoming-supply exception must cite that exception's deterministic evidence."
            )
    if action_type != EXPEDITE_ACTION_TYPE:
        return
    verified_by_id = {
        item.get("Exception_ID"): item for item in verified if isinstance(item, dict)
    } if isinstance(verified, list) else {}
    evidence_items = [item for item in action.get("evidence", []) if isinstance(item, dict)]
    scopes = [verified_by_id.get(item.get("exception_id"), structured_input) for item in evidence_items]
    if not any(
        isinstance(scope.get("Shortage_Quantity"), (int, float))
        and not isinstance(scope.get("Shortage_Quantity"), bool)
        and scope["Shortage_Quantity"] > 0
        for scope in scopes
    ):
        raise LLMRequestError("An incoming delivery cannot be recommended for expediting when shortage is zero.")
    any_positive_supply = any(
        isinstance(scope.get(field), (int, float))
        and not isinstance(scope.get(field), bool)
        and scope[field] > 0
        for scope in scopes for field in EXPEDITE_SUPPORT_FIELDS
    )
    if not any_positive_supply:
        eligible_only = any(
            isinstance(scope.get("Eligible_Incoming_Quantity"), (int, float))
            and not isinstance(scope.get("Eligible_Incoming_Quantity"), bool)
            and scope["Eligible_Incoming_Quantity"] > 0
            for scope in scopes
        )
        if eligible_only:
            raise LLMRequestError(
                "Python facts contain eligible on-time supply alone; this does not support expediting."
            )
        raise LLMRequestError(
            "Python facts contain no positive late or overdue incoming supply."
        )
    supported_scopes = []
    for item in evidence_items:
        scope = verified_by_id.get(item.get("exception_id"), structured_input)
        value = scope.get(item.get("field"))
        shortage_value = scope.get("Shortage_Quantity")
        if (
            item.get("field") in EXPEDITE_SUPPORT_FIELDS
            and isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0
            and isinstance(shortage_value, (int, float)) and not isinstance(shortage_value, bool)
            and shortage_value > 0
        ):
            supported_scopes.append(scope)
    if not supported_scopes:
        raise LLMRequestError(
            "Expediting evidence must cite a positive incoming-supply field from the same exception as the shortage."
        )


def _safe_openrouter_error(response: requests.Response) -> LLMConfigurationError | LLMRequestError:
    """Classify an OpenRouter error without exposing its raw body."""

    status = response.status_code
    try:
        payload = response.json()
        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        message = error.get("message", "") if isinstance(error, dict) else ""
        code = error.get("code", "") if isinstance(error, dict) else ""
    except (ValueError, TypeError, AttributeError):
        message, code = "", ""
    diagnostic = f"{code} {message} {getattr(response, 'text', '')}".lower()

    schema_markers = (
        "invalid schema", "schema is invalid", "unsupported schema", "schema keyword",
        "unsupported keyword", "minlength", "minitems", "uniqueitems", "additionalproperties",
        "invalid json schema",
    )
    model_markers = (
        "no endpoints found that support", "does not support structured", "doesn't support structured",
        "structured outputs not supported", "response_format is not supported",
        "response format is not supported", "unsupported response_format",
    )
    if status in (400, 422) and any(marker in diagnostic for marker in schema_markers):
        return LLMConfigurationError(
            "OpenRouter rejected the JSON Schema. Check for schema keywords unsupported "
            "by the provider. The request was not downgraded and no sensitive data is shown.",
            status, "schema_incompatible",
        )
    if status in (400, 404, 422) and any(marker in diagnostic for marker in model_markers):
        return LLMConfigurationError(
            "The selected model or routed provider does not support required strict "
            "Structured Outputs. Verify the model and supported parameters. Safety "
            "validation was not downgraded.",
            status, "structured_outputs_unsupported",
        )
    if status in (401, 403):
        return LLMConfigurationError(
            "OpenRouter authentication or access failed. Check the API key and account "
            "permissions. The key is not displayed.",
            status, "authentication",
        )
    if status == 402 or any(marker in diagnostic for marker in ("insufficient credit", "insufficient balance", "payment required")):
        return LLMConfigurationError(
            "OpenRouter has insufficient balance or credit. Check the account balance "
            "before retrying.",
            status, "balance",
        )
    return LLMRequestError(
        f"The OpenRouter request failed (HTTP {status}); deterministic Python results "
        "are unaffected.",
        status, "http_error",
    )


def _evidence_item(exception: dict[str, Any], field: str) -> dict[str, Any]:
    """Build evidence from Python facts; the model never supplies factual values or units."""

    return {
        "exception_id": exception["Exception_ID"],
        "field": field,
        "value": exception.get(field),
        "unit": exception.get("Quantity_Unit") if field in QUANTITY_EVIDENCE_FIELDS else None,
    }


def _first_evidence_field(exception: dict[str, Any], candidates: tuple[str, ...]) -> str:
    for field in candidates:
        if field in EVIDENCE_FIELDS and field in exception and exception.get(field) is not None:
            return field
    return "Analysis_Date"


def _deterministic_actions(structured_input: dict[str, Any]) -> list[dict[str, Any]]:
    """Derive action types and evidence only from the verified exception register."""

    verified = structured_input.get("Verified_Exceptions", [])
    if not isinstance(verified, list):
        verified = []
    groups: dict[str, list[dict[str, Any]]] = {
        "Escalate to procurement": [],
        "Request missing data": [],
        "Escalate to production planning": [],
    }
    for exception in verified:
        if not isinstance(exception, dict) or not isinstance(exception.get("Exception_ID"), str):
            continue
        exception_type = exception.get("Exception_Type")
        if exception_type == "MATERIAL_SHORTAGE":
            groups["Escalate to procurement"].append(exception)
        elif exception_type in {"LATE_INCOMING_SUPPLY", "OVERDUE_INCOMING_SUPPLY", "OVERDUE_INCOMING_PO"}:
            groups["Request missing data"].append(exception)
        elif exception_type in PRODUCTION_PLANNING_EXCEPTION_TYPES:
            groups["Escalate to production planning"].append(exception)
        else:
            groups["Request missing data"].append(exception)

    actions: list[dict[str, Any]] = []
    specifications = (
        (
            "Escalate to procurement",
            "Submit the verified material-shortage exceptions for human procurement review.",
            ("Shortage_Quantity", "Material_ID", "Python_Priority"),
        ),
        (
            "Request missing data",
            "Request the missing information needed for human review of the verified supply exceptions.",
            ("Late_Incoming_Quantity", "Overdue_Incoming_Quantity", "Next_Receipt_Date", "Material_ID"),
        ),
        (
            "Escalate to production planning",
            "Submit the verified production-planning exceptions for human planning review.",
            (
                "Planned_End_Date", "Requested_Delivery_Date", "Planned_Start_Date",
                "Days_After_Requested_Delivery", "Production_Order_ID", "Analysis_Date",
            ),
        ),
    )
    for action_type, action_text, candidates in specifications:
        exceptions = groups[action_type]
        if not exceptions:
            continue
        evidence = [
            _evidence_item(exception, _first_evidence_field(exception, candidates))
            for exception in exceptions
        ]
        actions.append({
            "action_type": action_type,
            "action": action_text,
            "evidence": evidence,
            "requires_human_approval": True,
            "execution_status": "NOT_EXECUTED",
        })
    if not actions and not verified:
        actions.append({
            "action_type": "Take no immediate action when supply is sufficient",
            "action": "No immediate action is proposed because the verified exception list is empty.",
            "evidence": [{
                "exception_id": None,
                "field": "Shortage_Quantity",
                "value": structured_input.get("Shortage_Quantity"),
                "unit": structured_input.get("Quantity_Unit"),
            }],
            "requires_human_approval": True,
            "execution_status": "NOT_EXECUTED",
        })
    return actions


def canonicalize_llm_output(raw_output: str, structured_input: dict[str, Any]) -> str:
    """Replace every model-supplied fact and action decision with verified Python data."""

    if not isinstance(raw_output, str) or not raw_output.strip():
        return raw_output
    text = raw_output.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return raw_output
    if not isinstance(parsed, dict):
        return raw_output

    parsed["python_priority"] = structured_input.get("Python_Priority")
    parsed["priority_rule_id"] = structured_input.get("Priority_Rule_ID")

    model_reviews = parsed.get("exception_reviews", [])
    narratives_by_id = {
        review.get("exception_id"): review
        for review in model_reviews
        if isinstance(review, dict) and isinstance(review.get("exception_id"), str)
    } if isinstance(model_reviews, list) else {}
    verified = structured_input.get("Verified_Exceptions", [])
    verified = verified if isinstance(verified, list) else []
    canonical_reviews = []
    for exception in verified:
        if not isinstance(exception, dict):
            continue
        exception_id = exception.get("Exception_ID")
        narrative = narratives_by_id.get(exception_id, {})
        finding = narrative.get("finding") if isinstance(narrative, dict) else None
        recommended_review = narrative.get("recommended_review") if isinstance(narrative, dict) else None
        if not isinstance(finding, str) or not finding.strip():
            material = exception.get("Material_ID")
            subject = f" for material {material}" if material else ""
            finding = f"Verified {exception.get('Exception_Type')} exception{subject} requires review."
        if not isinstance(recommended_review, str) or not recommended_review.strip():
            recommended_review = "Review this verified exception and confirm the appropriate next step."
        review = {
            output_field: exception.get(input_field)
            for output_field, input_field in EXCEPTION_REVIEW_FACT_FIELDS.items()
        }
        review.update({
            "finding": finding,
            "recommended_review": recommended_review,
            "requires_human_approval": True,
            "execution_status": "NOT_EXECUTED",
        })
        canonical_reviews.append(review)
    parsed["exception_reviews"] = canonical_reviews
    parsed["recommended_actions"] = _deterministic_actions(structured_input)
    required_codes = structured_input.get("Required_Missing_Information_Codes", [])
    parsed["missing_information_codes"] = list(required_codes) if isinstance(required_codes, list) else []
    return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))


def parse_llm_output(raw_output: str, structured_input: dict[str, Any]) -> dict[str, Any]:
    """Parse and validate the fixed JSON structure and evidence rules."""

    if not isinstance(raw_output, str) or not raw_output.strip():
        raise LLMRequestError("AI output is empty.")
    text = raw_output.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMRequestError("AI output is not valid JSON.") from exc
    if HAN_PATTERN.search(json.dumps(parsed, ensure_ascii=False)):
        raise LLMRequestError("AI output contains Chinese/Han characters; English-only output is required.")
    required = {
        "priority_summary", "explanation", "python_priority", "priority_rule_id",
        "exception_reviews", "recommended_actions", "missing_information_codes",
    }
    if not isinstance(parsed, dict) or set(parsed) != required:
        raise LLMRequestError("AI output fields must exactly match the fixed structure.")
    for field in ("priority_summary", "explanation", "python_priority", "priority_rule_id"):
        if not isinstance(parsed[field], str) or not parsed[field].strip():
            raise LLMRequestError("AI returned empty required text.")
    for field in ("priority_summary", "explanation"):
        if UNSUPPORTED_SEVERITY_PATTERN.search(parsed[field]):
            raise LLMRequestError(
                "AI narrative adds a subjective severity label not supplied by Python facts."
            )
        if UNSUPPORTED_DELAY_CLAIM_PATTERN.search(parsed[field]):
            raise LLMRequestError(
                "AI narrative calls a receipt delayed without date-change evidence."
            )
    if structured_input.get("Order_Has_Material_Shortage") is True:
        order_narrative = " ".join((parsed["priority_summary"], parsed["explanation"]))
        if any(pattern.search(order_narrative) for pattern in ORDER_SUPPLY_SUFFICIENT_PATTERNS):
            raise LLMRequestError(
                "AI narrative describes an order with a verified shortage as supply-sufficient."
            )
    if parsed["python_priority"] != structured_input.get("Python_Priority") or parsed["priority_rule_id"] != structured_input.get("Priority_Rule_ID"):
        raise LLMRequestError("AI priority does not match deterministic Python facts.")
    reviews = parsed["exception_reviews"]
    expected_exceptions = structured_input.get("Verified_Exceptions", [])
    if not isinstance(expected_exceptions, list):
        expected_exceptions = []
    if not isinstance(reviews, list):
        raise LLMRequestError("exception_reviews must be a list.")
    if len(reviews) != len(expected_exceptions):
        raise LLMRequestError(
            "exception_reviews must contain exactly one review for every verified exception."
        )
    expected_exception_by_id = {
        item.get("Exception_ID"): item
        for item in expected_exceptions
        if isinstance(item, dict) and isinstance(item.get("Exception_ID"), str)
    }
    review_fields = {
        "exception_id", "exception_type", "material_id", "priority",
        "material_need_date", "quantity_unit", "shortage_quantity", "late_incoming_quantity",
        "overdue_incoming_quantity", "next_receipt_date", "requested_delivery_date",
        "planned_start_date", "planned_end_date", "days_after_requested_delivery",
        "impact_class", "direct_order_impact", "supply_relationship", "directly_pegged_to_order",
        "finding", "recommended_review",
        "requires_human_approval", "execution_status",
    }
    copied_fields = EXCEPTION_REVIEW_FACT_FIELDS
    seen_exception_ids: set[str] = set()
    for review, expected in zip(reviews, expected_exceptions):
        if not isinstance(review, dict) or set(review) != review_fields:
            raise LLMRequestError("Each exception review must exactly match the fixed structure.")
        for output_field, input_field in copied_fields.items():
            if not _same_value(review[output_field], expected.get(input_field)):
                raise LLMRequestError(
                    f"Exception review field {output_field} does not match Python facts."
                )
        exception_id = review["exception_id"]
        if exception_id in seen_exception_ids:
            raise LLMRequestError("Exception review IDs must be unique.")
        seen_exception_ids.add(exception_id)
        for field in ("finding", "recommended_review"):
            if not isinstance(review[field], str) or not review[field].strip():
                raise LLMRequestError("Exception review narrative fields cannot be empty.")
            if any(marker in review[field].lower() for marker in EXECUTION_CLAIM_MARKERS):
                raise LLMRequestError("Exception review text claims execution already occurred.")
            if UNSUPPORTED_SEVERITY_PATTERN.search(review[field]):
                raise LLMRequestError(
                    "Exception review adds a subjective severity label not supplied by Python facts."
                )
            if UNSUPPORTED_DELAY_CLAIM_PATTERN.search(review[field]):
                raise LLMRequestError(
                    "Exception review calls a receipt delayed without date-change evidence."
                )
        if review["requires_human_approval"] is not True:
            raise LLMRequestError("Every exception review must require human approval.")
        if review["execution_status"] != "NOT_EXECUTED":
            raise LLMRequestError("Every exception review must remain NOT_EXECUTED.")
    if not isinstance(parsed["recommended_actions"], list):
        raise LLMRequestError("Recommended Actions must be a list.")
    request_missing_evidence_ids: set[str] = set()
    action_evidence_ids: set[str] = set()
    evidence_ids_by_action_type: dict[str, set[str]] = {}
    for action in parsed["recommended_actions"]:
        action_fields = {"action_type", "action", "evidence", "requires_human_approval", "execution_status"}
        if not isinstance(action, dict) or set(action) != action_fields:
            raise LLMRequestError("Action fields do not match the fixed structure.")
        if action["action_type"] not in ALLOWED_ACTION_TYPES:
            raise LLMRequestError("AI returned a disallowed action type because Python lacks the required supporting facts.")
        if not isinstance(action["action"], str) or not action["action"].strip():
            raise LLMRequestError("Action text cannot be empty.")
        if any(marker in action["action"].lower() for marker in EXECUTION_CLAIM_MARKERS):
            raise LLMRequestError("Action text claims execution already occurred.")
        if UNSUPPORTED_SEVERITY_PATTERN.search(action["action"]):
            raise LLMRequestError(
                "Recommended action adds a subjective severity label not supplied by Python facts."
            )
        if UNSUPPORTED_DELAY_CLAIM_PATTERN.search(action["action"]):
            raise LLMRequestError(
                "Recommended action calls a receipt delayed without date-change evidence."
            )
        if action["requires_human_approval"] is not True:
            raise LLMRequestError("Every action must require human approval.")
        if action["execution_status"] != "NOT_EXECUTED":
            raise LLMRequestError("AI must not claim an action was executed.")
        evidence = action["evidence"]
        if not isinstance(evidence, list) or not evidence:
            raise LLMRequestError("Every action must include Evidence.")
        for item in evidence:
            if not isinstance(item, dict) or set(item) != {"exception_id", "field", "value", "unit"}:
                raise LLMRequestError("Evidence fields do not match the fixed structure.")
            field = item["field"]
            exception_id = item["exception_id"]
            if exception_id is None:
                evidence_scope = structured_input
            elif isinstance(exception_id, str) and exception_id in expected_exception_by_id:
                evidence_scope = expected_exception_by_id[exception_id]
            else:
                raise LLMRequestError("Evidence references an unknown exception ID.")
            if isinstance(exception_id, str):
                action_evidence_ids.add(exception_id)
                evidence_ids_by_action_type.setdefault(action["action_type"], set()).add(exception_id)
            if field not in EVIDENCE_FIELDS:
                raise LLMRequestError("Evidence references a disallowed field.")
            if field in evidence_scope:
                expected_value = evidence_scope[field]
            elif field == "Python_Priority" and "Priority" in evidence_scope:
                # Backwards compatibility for order payloads produced before
                # the exception-scoped Python_Priority alias was explicit.
                expected_value = evidence_scope["Priority"]
            else:
                raise LLMRequestError("Evidence references a disallowed field.")
            if not _same_value(item["value"], expected_value):
                raise LLMRequestError(
                    "AI output was rejected: an evidence value does not match the verified Python facts. "
                    "No AI advice was accepted or displayed."
                )
            expected_unit = evidence_scope.get("Quantity_Unit") if field in QUANTITY_EVIDENCE_FIELDS else None
            if item["unit"] != expected_unit:
                raise LLMRequestError(
                    f"AI output was rejected: evidence {exception_id or 'top-level'}.{field} "
                    f"unit does not match Python facts; expected {expected_unit!r}, "
                    f"but received {item['unit']!r}. "
                    "No AI advice was accepted or displayed."
                )
            if action["action_type"] == REQUEST_MISSING_DATA_ACTION_TYPE and isinstance(exception_id, str):
                request_missing_evidence_ids.add(exception_id)
        validate_action_support(action, structured_input)
    codes = parsed["missing_information_codes"]
    if not isinstance(codes, list) or any(code not in MISSING_INFORMATION_CODES for code in codes):
        raise LLMRequestError("Missing Information contains an unknown code.")
    if len(codes) != len(set(codes)):
        raise LLMRequestError("Missing Information codes must be unique.")
    expected_exception_ids = set(expected_exception_by_id)
    if not expected_exception_ids.issubset(action_evidence_ids):
        raise LLMRequestError(
            "Recommended actions must include exception-scoped evidence covering every verified exception."
        )
    required_codes = structured_input.get("Required_Missing_Information_Codes")
    if isinstance(required_codes, list) and set(codes) != set(required_codes):
        raise LLMRequestError(
            "Missing information codes must exactly match the deterministic order-scoped requirements."
        )
    supply_review_ids = {
        item["Exception_ID"] for item in expected_exceptions
        if item.get("Exception_Type") in {"LATE_INCOMING_SUPPLY", "OVERDUE_INCOMING_SUPPLY"}
    }
    if not supply_review_ids.issubset(request_missing_evidence_ids):
        raise LLMRequestError(
            "Every late or overdue incoming-supply exception requires an evidence-bound missing-data review."
        )
    shortage_ids = {
        item["Exception_ID"] for item in expected_exceptions
        if item.get("Exception_Type") == "MATERIAL_SHORTAGE"
    }
    if not shortage_ids.issubset(evidence_ids_by_action_type.get("Escalate to procurement", set())):
        raise LLMRequestError(
            "Every material-shortage exception requires an evidence-bound procurement review action."
        )
    production_planning_ids = {
        item["Exception_ID"] for item in expected_exceptions
        if item.get("Exception_Type") in PRODUCTION_PLANNING_EXCEPTION_TYPES
    }
    if not production_planning_ids.issubset(
        evidence_ids_by_action_type.get("Escalate to production planning", set())
    ):
        raise LLMRequestError(
            "Production backlog and unscheduled-order exceptions require an evidence-bound production-planning review action."
        )
    return parsed


def generate_explanation(
    structured_input: dict[str, Any], api_key: str | None = None
) -> LLMResult:
    """Call OpenRouter with a caller-supplied or local environment key.

    The key is used only in the Authorization header. It is never added to
    the structured payload, returned result, cache key, or evaluation ledger.
    Deterministic Python results remain unchanged when the call fails.
    """

    resolved_api_key = (api_key or configured_api_key()).strip()
    if not resolved_api_key or resolved_api_key == "your_api_key_here":
        raise LLMConfigurationError(
            "An OpenRouter API Key is required for AI generation. "
            "Deterministic Python analysis remains available without it."
        )
    model = configured_model()
    started = time.perf_counter()
    try:
        response = requests.post(
            OPENROUTER_API_URL,
            headers={"Authorization": f"Bearer {resolved_api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": build_messages(structured_input),
                "temperature": 0,
                "max_tokens": LLM_MAX_OUTPUT_TOKENS,
                "usage": {"include": True},
                "response_format": build_response_format(),
                "provider": {"require_parameters": True},
            },
            timeout=LLM_REQUEST_TIMEOUT_SECONDS,
        )
        if not 200 <= response.status_code < 300:
            raise _safe_openrouter_error(response)
        response.raise_for_status()
        payload = response.json()
        raw_output = payload["choices"][0]["message"]["content"]
    except LLMConfigurationError:
        raise
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as exc:
        raise LLMRequestError(
            "The AI service call failed; deterministic Python results are unaffected. "
            "Check the key, network, and provider status, then retry.",
            category="request_transport",
        ) from exc
    metadata = extract_response_metadata(
        payload, model, resolved_api_key, time.perf_counter() - started, raw_output
    )
    finish_reason = payload["choices"][0].get("finish_reason")
    if finish_reason == "length":
        error = LLMRequestError(
            "AI output was incomplete because it reached the configured output-token limit. "
            "No partial advice was accepted or displayed. Retry with the current configuration."
        )
        error.response_metadata = metadata
        raise error
    try:
        canonical_output = canonicalize_llm_output(raw_output, structured_input)
        parsed = parse_llm_output(canonical_output, structured_input)
    except LLMRequestError as exc:
        exc.response_metadata = metadata
        raise
    return LLMResult(
        parsed_output=parsed,
        raw_output=raw_output,
        model=metadata["model"], input_tokens=metadata["input_tokens"],
        output_tokens=metadata["output_tokens"], total_tokens=metadata["total_tokens"],
        response_time_seconds=metadata["response_time_seconds"], generation_id=metadata["generation_id"],
        exact_cost_usd=metadata["exact_cost_usd"], estimated_cost_usd=metadata["estimated_cost_usd"],
        pricing_source=metadata["pricing_source"], pricing_as_of=metadata["pricing_as_of"],
    )
