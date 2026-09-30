"""Phase 7 manifest, call ledger, and rating-template helpers."""

import csv
import hashlib
import json
from collections import Counter
from functools import lru_cache
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from config.settings import (
    DEFAULT_OPENROUTER_MODEL, LLM_MAX_OUTPUT_TOKENS,
    MODEL_PRICING_USD_PER_MILLION_TOKENS,
)
from src.llm_client import (
    LLMConfigurationError, LLMRequestError, LLMResult, canonicalize_llm_output,
    generate_explanation, parse_llm_output,
)
from src.llm_prompt import PROMPT_VERSION, SCHEMA_VERSION
from src.ai_action_plan import build_order_ai_input
from src.exception_engine import build_exception_register
from src.order_summary import build_order_summary
from src.shortage_engine import run_shortage_analysis
from src.validators import validate_workbook
from src.workbook_reader import read_workbook


ANALYSIS_DATE = date(2026, 9, 25)
TEMPERATURE = 0
SAMPLING_SEED = 6201
SAMPLES_PER_WORKBOOK = 4
RATINGS = {"Supported", "Partially Supported", "Unsupported", "Contradictory"}
MANIFEST_FIELDS = [
    "evaluation_run_id", "scenario_id", "workbook_name", "workbook_sha256",
    "validation_status", "data_error_count", "result_row_count", "planned_llm_calls",
    "blocked_before_llm", "result_key", "result_identity", "selected_order", "selection_reason",
    "sampling_seed", "selection_rank", "sampling_stratum",
]
RATING_FIELDS = [
    "rating_key", "evaluation_run_id", "scenario_id", "result_key", "action_index",
    "action_type", "action_text", "evidence_json", "python_priority", "shortage_quantity",
    "eligible_incoming_quantity", "late_incoming_quantity", "overdue_incoming_quantity",
    "suggested_rule_flags", "human_rating", "human_reason", "reviewer", "reviewed_at",
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _result_key(scenario_id: str, facts: dict[str, Any]) -> str:
    selected = facts.get("Selected_Order", {})
    fields = ("Sales_Order_ID", "Sales_Order_Item")
    return "|".join([scenario_id, *(str(selected.get(field, "")) for field in fields)])


def _source_version(project_root: Path) -> str:
    paths = [project_root / "evaluate_phase7.py", project_root / "config" / "settings.py"]
    paths.extend(sorted((project_root / "src").glob("*.py")))
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(project_root).as_posix().encode())
        digest.update(path.read_bytes())
    return f"source-sha256:{digest.hexdigest()}"


def _run_id(scenario_ids: list[str], workbook_hashes: dict[str, str], code_version: str,
             pricing_as_of: str) -> str:
    fixed = "|".join([
        *scenario_ids, ANALYSIS_DATE.isoformat(), DEFAULT_OPENROUTER_MODEL,
        PROMPT_VERSION, SCHEMA_VERSION, str(TEMPERATURE), str(LLM_MAX_OUTPUT_TOKENS),
        pricing_as_of, code_version, str(SAMPLING_SEED), str(SAMPLES_PER_WORKBOOK),
        *(f"{scenario}:{workbook_hashes[scenario]}" for scenario in scenario_ids),
    ])
    return f"phase7-{hashlib.sha256(fixed.encode()).hexdigest()[:12]}"


def _seeded_rank(*parts: Any) -> str:
    """Return a stable cross-process rank for fixed-seed sampling."""

    text = "|".join(str(part) for part in (SAMPLING_SEED, *parts))
    return hashlib.sha256(text.encode()).hexdigest()


def _sampling_stratum(facts: dict[str, Any]) -> str:
    shortage = "SHORTAGE" if facts.get("Order_Has_Material_Shortage") else "NO_SHORTAGE"
    truncated = "TRUNCATED" if facts.get("payload_truncated") else "COMPLETE"
    return "|".join([
        str(facts.get("Primary_Exception_Type")), shortage,
        str(facts.get("Python_Priority")), truncated,
    ])


def _stratified_sample(candidates: list[dict[str, Any]], scenario_id: str) -> list[dict[str, Any]]:
    """Select four orders per workbook across available strata with a fixed seed."""

    groups: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        groups.setdefault(candidate["sampling_stratum"], []).append(candidate)
    for stratum, rows in groups.items():
        rows.sort(key=lambda row: _seeded_rank(scenario_id, stratum, row["result_key"]))
    stratum_order = sorted(groups, key=lambda stratum: _seeded_rank(scenario_id, stratum))
    selected: list[dict[str, Any]] = []
    while len(selected) < min(SAMPLES_PER_WORKBOOK, len(candidates)):
        progressed = False
        for stratum in stratum_order:
            if groups[stratum] and len(selected) < SAMPLES_PER_WORKBOOK:
                selected.append(groups[stratum].pop(0))
                progressed = True
        if not progressed:
            break
    return selected


def _manifest_workbooks(
    project_root: Path, *, include_expanded_medium: bool
) -> dict[str, Path]:
    """Resolve the 25 formal synthetic ERP workbooks."""
    catalog_path = project_root / "data" / "expanded_scenarios" / "scenario_catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    workbooks = {item["scenario_id"]: project_root / item["Workbook Path"] for item in catalog["scenarios"]}
    missing = [str(path) for path in workbooks.values() if not path.is_file()]
    if missing:
        raise ValueError(
            "Required evaluation workbooks are missing. Generate the expanded workbooks first: "
            + ", ".join(missing)
        )
    return workbooks


@lru_cache(maxsize=4)
def build_manifest(
    project_root: Path, *, include_expanded_medium: bool = False
) -> dict[str, Any]:
    """Build a fixed, sorted evaluation plan without API access.

    Four order items are selected per formal workbook using a fixed-seed,
    round-robin stratified sample, then the exact UI payload is frozen.
    """

    workbooks = _manifest_workbooks(
        project_root, include_expanded_medium=include_expanded_medium
    )
    scenario_ids = sorted(workbooks)
    workbook_hashes = {scenario_id: _sha256(path) for scenario_id, path in workbooks.items()}
    pricing = MODEL_PRICING_USD_PER_MILLION_TOKENS[DEFAULT_OPENROUTER_MODEL]
    code_version = _source_version(project_root)
    run_id = _run_id(scenario_ids, workbook_hashes, code_version, pricing["as_of"])
    entries: list[dict[str, Any]] = []
    eligible_order_totals: dict[str, int] = {}
    eligible_exception_totals: dict[str, int] = {}
    for scenario_id in scenario_ids:
        workbook = workbooks[scenario_id]
        sheets = read_workbook(workbook)
        report = validate_workbook(sheets, ANALYSIS_DATE)
        base = {
            "evaluation_run_id": run_id, "scenario_id": scenario_id,
            "workbook_name": workbook.name, "workbook_sha256": workbook_hashes[scenario_id],
            "validation_status": "VALID" if report.is_valid else "DATA_ERROR",
            "data_error_count": len(report.data_errors),
            "blocked_before_llm": not report.is_valid,
        }
        if not report.is_valid:
            entries.append({**base, "result_row_count": 0, "planned_llm_calls": 0,
                            "result_key": "", "result_identity": {}, "structured_input": None})
            continue
        result = run_shortage_analysis(sheets, ANALYSIS_DATE, validation_report=report)
        rows = result.shortage_results
        if rows.empty:
            entries.append({**base, "result_row_count": 0, "planned_llm_calls": 0,
                            "result_key": "", "result_identity": {}, "structured_input": None})
        else:
            exceptions = build_exception_register(sheets, result, ANALYSIS_DATE)
            eligible = exceptions[
                exceptions["Sales_Order_ID"].notna()
            ].copy()
            eligible_order_count = int(
                eligible[["Sales_Order_ID", "Sales_Order_Item"]].drop_duplicates().shape[0]
            )
            eligible_exception_count = int(len(eligible))
            eligible_order_totals[scenario_id] = eligible_order_count
            eligible_exception_totals[scenario_id] = eligible_exception_count
            eligible_exception_types = dict(Counter(eligible["Exception_Type"]))
            order_summary = build_order_summary(eligible, sheets["Orders"])
            if order_summary.empty:
                entries.append({**base, "result_row_count": len(rows), "planned_llm_calls": 0,
                                "result_key": "", "result_identity": {}, "structured_input": None,
                            "selected_order": {}, "selection_reason": "No LLM-eligible order-level exception."})
                continue
            candidates: list[dict[str, Any]] = []
            for selected in order_summary.itertuples(index=False):
                order_id, order_item = str(selected.Sales_Order_ID), str(selected.Sales_Order_Item)
                preview = build_order_ai_input(order_id, order_item, exceptions, rows, sheets)
                facts = preview["llm_payload"]
                identity = {"Sales_Order_ID": order_id, "Sales_Order_Item": order_item}
                candidates.append({
                    "selected_order": identity,
                    "result_key": _result_key(scenario_id, facts),
                    "result_identity": identity,
                    "structured_input": facts,
                    "sampling_stratum": _sampling_stratum(facts),
                })
            sampled = _stratified_sample(candidates, scenario_id)
            if len(sampled) != SAMPLES_PER_WORKBOOK:
                raise ValueError(
                    f"{scenario_id} has only {len(sampled)} eligible orders; "
                    f"{SAMPLES_PER_WORKBOOK} are required for the fixed 100-call design."
                )
            for selection_rank, candidate in enumerate(sampled, start=1):
                facts = candidate["structured_input"]
                entries.append({
                    **base, **candidate, "result_row_count": len(rows), "planned_llm_calls": 1,
                    "eligible_order_count": eligible_order_count,
                    "eligible_exception_count": eligible_exception_count,
                    "eligible_exception_types": eligible_exception_types,
                    "selected_exception_types": dict(Counter(
                        item["Exception_Type"] for item in facts.get("Verified_Exceptions", [])
                    )),
                    "selection_reason": (
                        "Fixed-seed stratified sample: four orders per workbook; strata combine "
                        "primary exception type, shortage status, Python priority, and payload truncation."
                    ),
                    "sampling_seed": SAMPLING_SEED,
                    "selection_rank": selection_rank,
                })
    entries.sort(key=lambda item: (item["scenario_id"], item.get("selection_rank", 0), item["result_key"]))
    planned = sum(item["planned_llm_calls"] for item in entries)
    low_per_call = 1_000 / 1_000_000 * pricing["input"] + 200 / 1_000_000 * pricing["output"]
    high_per_call = 10_000 / 1_000_000 * pricing["input"] + LLM_MAX_OUTPUT_TOKENS / 1_000_000 * pricing["output"]
    return {
        "evaluation_run_id": run_id, "created_for_analysis_date": ANALYSIS_DATE.isoformat(),
        "evaluation_scope": "Fixed-seed stratified sample of four order-level fact packages per workbook; not an all-order correctness claim.",
        "sampling_seed": SAMPLING_SEED,
        "samples_per_workbook": SAMPLES_PER_WORKBOOK,
        "eligible_order_count": sum(eligible_order_totals.values()),
        "eligible_exception_count": sum(eligible_exception_totals.values()),
        "scenario_count": len(scenario_ids), "model": DEFAULT_OPENROUTER_MODEL,
        "prompt_version": PROMPT_VERSION, "schema_version": SCHEMA_VERSION,
        "temperature": TEMPERATURE, "max_tokens": LLM_MAX_OUTPUT_TOKENS,
        "code_version": code_version,
        "pricing_source": pricing["source"], "pricing_as_of": pricing["as_of"],
        "planned_llm_calls": planned,
        "estimated_cost_range_usd": [round(planned * low_per_call, 6), round(planned * high_per_call, 6)],
        "estimated_cost_note": "Estimate only; not a final bill.",
        "entries": entries,
    }


def write_manifest(manifest: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    existing_path = output_dir / "evaluation_manifest.json"
    ledger_path = output_dir / "llm_calls.jsonl"
    if existing_path.exists() and ledger_path.exists() and ledger_path.stat().st_size:
        existing = json.loads(existing_path.read_text(encoding="utf-8"))
        if existing.get("evaluation_run_id") != manifest["evaluation_run_id"]:
            raise ValueError(
                "Existing call ledger belongs to a different evaluation run; archive results/phase7 before prepare."
            )
    (output_dir / "evaluation_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (output_dir / "evaluation_manifest.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        for item in manifest["entries"]:
            row = {key: item.get(key) for key in MANIFEST_FIELDS}
            row["result_identity"] = json.dumps(row["result_identity"], ensure_ascii=False, sort_keys=True)
            writer.writerow(row)


def load_calls(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append_call(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()


def call_matches_manifest(call: dict[str, Any], entry: dict[str, Any], manifest: dict[str, Any]) -> bool:
    return (
        call.get("evaluation_run_id") == manifest["evaluation_run_id"]
        and call.get("result_key") == entry["result_key"]
        and call.get("workbook_sha256") == entry["workbook_sha256"]
        and call.get("model") == manifest["model"]
        and call.get("prompt_version") == manifest["prompt_version"]
        and call.get("schema_version") == manifest["schema_version"]
        and call.get("structured_input") == entry["structured_input"]
    )


def matching_calls(manifest: dict[str, Any], calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries = {entry["result_key"]: entry for entry in manifest["entries"] if entry["result_key"]}
    return [call for call in calls if call.get("result_key") in entries and call_matches_manifest(call, entries[call["result_key"]], manifest)]


def pending_entries(manifest: dict[str, Any], calls: list[dict[str, Any]], *, resume: bool, retry_failed: bool) -> list[dict[str, Any]]:
    calls = matching_calls(manifest, calls)
    attempted: dict[str, list[dict[str, Any]]] = {}
    for call in calls:
        attempted.setdefault(call["result_key"], []).append(call)
    pending = []
    for entry in manifest["entries"]:
        if not entry["planned_llm_calls"]:
            continue
        history = attempted.get(entry["result_key"], [])
        if any(item.get("success") for item in history):
            continue
        if not history:
            pending.append(entry)
        elif retry_failed:
            pending.append(entry)
        elif not resume:
            continue
    return pending


def execute_calls(
    manifest: dict[str, Any], ledger_path: Path, *, max_calls: int,
    resume: bool = False, retry_failed: bool = False,
    generator: Callable[[dict[str, Any]], LLMResult] = generate_explanation,
) -> int:
    calls = load_calls(ledger_path)
    pending = pending_entries(manifest, calls, resume=resume, retry_failed=retry_failed)
    if max_calls < 0 or max_calls > len(pending):
        raise ValueError("max_calls exceeds the current pending manifest scope")
    completed = 0
    for entry in pending[:max_calls]:
        history = [item for item in calls if item["result_key"] == entry["result_key"]]
        attempt = max((item.get("attempt_number", 0) for item in history), default=0) + 1
        started = datetime.now(timezone.utc)
        record = {
            "evaluation_run_id": manifest["evaluation_run_id"], "scenario_id": entry["scenario_id"],
            "workbook_name": entry["workbook_name"], "workbook_sha256": entry["workbook_sha256"],
            "analysis_date": manifest["created_for_analysis_date"], "result_key": entry["result_key"],
            **entry["result_identity"], "model": manifest["model"],
            "prompt_version": manifest["prompt_version"], "schema_version": manifest["schema_version"],
            "attempt_number": attempt, "started_at": started.isoformat(),
            "structured_input": entry["structured_input"],
        }
        try:
            result = generator(entry["structured_input"])
            output = result.parsed_output
            record.update({
                "completed_at": datetime.now(timezone.utc).isoformat(), "success": True,
                "safe_error_category": None, "structured_validation_passed": True,
                "generation_id": result.generation_id, "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens, "total_tokens": result.total_tokens,
                "response_time_seconds": result.response_time_seconds,
                "exact_cost_usd": result.exact_cost_usd, "estimated_cost_usd": result.estimated_cost_usd,
                "pricing_source": result.pricing_source, "pricing_as_of": result.pricing_as_of,
                "parsed_output": output, "raw_output": result.raw_output,
                "python_priority_consistent": output["python_priority"] == entry["structured_input"]["Python_Priority"],
                "priority_rule_id_consistent": output["priority_rule_id"] == entry["structured_input"]["Priority_Rule_ID"],
                "obvious_numeric_contradiction": False, "execution_claim_detected": False,
                "contains_recommendation": bool(output["recommended_actions"]),
                "missing_information_codes_valid": True, "human_notes": "",
            })
        except (LLMConfigurationError, LLMRequestError) as exc:
            metadata = exc.response_metadata if isinstance(exc, LLMRequestError) and exc.response_metadata else {}
            record.update({
                "completed_at": datetime.now(timezone.utc).isoformat(), "success": False,
                "safe_error_category": exc.category, "structured_validation_passed": False,
                "model": metadata.get("model", manifest["model"]),
                "generation_id": metadata.get("generation_id"), "input_tokens": metadata.get("input_tokens"),
                "output_tokens": metadata.get("output_tokens"), "total_tokens": metadata.get("total_tokens"),
                "response_time_seconds": metadata.get("response_time_seconds", (datetime.now(timezone.utc) - started).total_seconds()),
                "exact_cost_usd": metadata.get("exact_cost_usd"), "estimated_cost_usd": metadata.get("estimated_cost_usd"),
                "pricing_source": metadata.get("pricing_source", manifest["pricing_source"]),
                "pricing_as_of": metadata.get("pricing_as_of", manifest["pricing_as_of"]),
                "parsed_output": None, "raw_output": metadata.get("raw_output"),
                "python_priority_consistent": None, "priority_rule_id_consistent": None,
                "obvious_numeric_contradiction": None, "execution_claim_detected": None,
                "contains_recommendation": None, "missing_information_codes_valid": None,
                "human_notes": str(exc),
            })
        append_call(ledger_path, record)
        calls.append(record)
        completed += 1
    return completed


def revalidate_failed_outputs(manifest: dict[str, Any], ledger_path: Path) -> int:
    """Append zero-cost local revalidation records after validator-only fixes."""

    calls = matching_calls(manifest, load_calls(ledger_path))
    histories: dict[str, list[dict[str, Any]]] = {}
    for call in calls:
        histories.setdefault(call["result_key"], []).append(call)
    appended = 0
    for result_key, history in histories.items():
        latest = max(history, key=lambda item: item.get("attempt_number", 0))
        if latest.get("success") or not latest.get("raw_output"):
            continue
        try:
            canonical = canonicalize_llm_output(latest["raw_output"], latest["structured_input"])
            output = parse_llm_output(canonical, latest["structured_input"])
        except LLMRequestError:
            continue
        now = datetime.now(timezone.utc).isoformat()
        record = {
            **latest,
            "attempt_number": latest.get("attempt_number", 0) + 1,
            "started_at": now,
            "completed_at": now,
            "success": True,
            "safe_error_category": None,
            "structured_validation_passed": True,
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "response_time_seconds": 0.0,
            "exact_cost_usd": None,
            "estimated_cost_usd": None,
            "parsed_output": output,
            "python_priority_consistent": True,
            "priority_rule_id_consistent": True,
            "obvious_numeric_contradiction": False,
            "execution_claim_detected": False,
            "contains_recommendation": bool(output["recommended_actions"]),
            "missing_information_codes_valid": True,
            "human_notes": (
                "Local revalidation of the same paid response after narrowing the "
                "receipt-delay phrase matcher; no new API call or token charge."
            ),
            "revalidated_from_attempt": latest.get("attempt_number"),
        }
        append_call(ledger_path, record)
        appended += 1
    return appended


def _flags(call: dict[str, Any], action: dict[str, Any]) -> list[str]:
    facts = call["structured_input"]
    flags = []
    incoming = [facts.get(key) for key in (
        "Eligible_Incoming_Quantity", "Late_Incoming_Quantity", "Overdue_Incoming_Quantity"
    )]
    if action["action_type"] == "Check whether an incoming delivery can be expedited" and not any(
        isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0 for value in incoming
    ):
        flags.append("EXPEDITE_WITHOUT_INCOMING")
    if action["action_type"] == "Take no immediate action when supply is sufficient" and facts.get("Shortage_Quantity", 0) > 0:
        flags.append("NO_ACTION_WITH_SHORTAGE")
    if call.get("parsed_output", {}).get("python_priority") != facts.get("Python_Priority"):
        flags.append("PRIORITY_MISMATCH")
    if call.get("execution_claim_detected"):
        flags.append("EXECUTION_CLAIM")
    return flags


def generate_ratings(calls: list[dict[str, Any]], path: Path) -> list[dict[str, Any]]:
    existing = {}
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as handle:
            existing = {row["rating_key"]: row for row in csv.DictReader(handle)}
    histories: dict[str, list[dict[str, Any]]] = {}
    for call in calls:
        histories.setdefault(call["result_key"], []).append(call)
    final_calls = [max(history, key=lambda item: item.get("attempt_number", 0)) for history in histories.values()]
    rows = []
    for call in sorted((item for item in final_calls if item.get("success")), key=lambda item: item["result_key"]):
        output = call["parsed_output"]
        facts = call["structured_input"]
        for index, action in enumerate(output["recommended_actions"], start=1):
            key = f"{call['evaluation_run_id']}|{call['result_key']}|{index}"
            prior = existing.get(key, {})
            rows.append({
                "rating_key": key, "evaluation_run_id": call["evaluation_run_id"],
                "scenario_id": call["scenario_id"], "result_key": call["result_key"],
                "action_index": index, "action_type": action["action_type"], "action_text": action["action"],
                "evidence_json": json.dumps(action["evidence"], ensure_ascii=False, sort_keys=True),
                "python_priority": facts["Python_Priority"], "shortage_quantity": facts["Shortage_Quantity"],
                "eligible_incoming_quantity": facts["Eligible_Incoming_Quantity"],
                "late_incoming_quantity": facts["Late_Incoming_Quantity"],
                "overdue_incoming_quantity": facts["Overdue_Incoming_Quantity"],
                "suggested_rule_flags": "|".join(_flags(call, action)),
                "human_rating": prior.get("human_rating", ""), "human_reason": prior.get("human_reason", ""),
                "reviewer": prior.get("reviewer", ""), "reviewed_at": prior.get("reviewed_at", ""),
            })
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RATING_FIELDS)
        writer.writeheader(); writer.writerows(rows)
    return rows


def validate_ratings(rows: list[dict[str, Any]]) -> None:
    invalid = sorted({row.get("human_rating", "") for row in rows if row.get("human_rating", "") not in RATINGS | {""}})
    if invalid:
        raise ValueError(f"Invalid human_rating values: {invalid}")
