"""Recompute and verify every Phase 7 fact package before paid calls."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.ai_action_plan import build_order_ai_input
from src.analysis_service import analyze_workbook_content
from src.phase7_evaluation import _source_version


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--compatibility-mode",
        action="store_true",
        help=(
            "Allow a source-version difference while still requiring exact payload "
            "rebuilds. Use only for a public packaging/UI-only revision."
        ),
    )
    args = parser.parse_args()

    project_root = PROJECT_ROOT
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    entries = manifest["entries"]
    failures: list[str] = []
    scenario_counts = Counter(entry["scenario_id"] for entry in entries)
    result_keys = [entry["result_key"] for entry in entries]

    if len(entries) != 100:
        failures.append(f"Expected 100 entries, found {len(entries)}")
    if len(scenario_counts) != 25 or set(scenario_counts.values()) != {4}:
        failures.append(f"Expected four entries for each of 25 scenarios: {dict(scenario_counts)}")
    if len(set(result_keys)) != len(result_keys):
        failures.append("Result keys are not unique")
    if any(entry["validation_status"] != "VALID" for entry in entries):
        failures.append("At least one selected workbook is not valid")

    current_source_version = _source_version(project_root)
    source_version_matches = manifest["code_version"] == current_source_version
    if not source_version_matches and not args.compatibility_mode:
        failures.append("Manifest source fingerprint does not match current code")

    catalog = json.loads(
        (project_root / "data" / "expanded_scenarios" / "scenario_catalog.json").read_text(encoding="utf-8")
    )["scenarios"]
    workbook_by_scenario = {
        row["Scenario ID"]: project_root / row["Workbook Path"] for row in catalog
    }
    analyses = {
        scenario_id: analyze_workbook_content(path.read_bytes(), __import__("datetime").date(2026, 9, 25))
        for scenario_id, path in workbook_by_scenario.items()
    }

    verified_exception_count = 0
    payload_hashes: list[str] = []
    import hashlib

    for entry in entries:
        scenario_id = entry["scenario_id"]
        selected = entry["selected_order"]
        analyzed = analyses[scenario_id]
        rebuilt = build_order_ai_input(
            selected["Sales_Order_ID"], selected["Sales_Order_Item"],
            analyzed.exceptions, analyzed.result.shortage_results, analyzed.sheets,
        )["llm_payload"]
        expected = entry["structured_input"]
        if rebuilt != expected:
            failures.append(f"{entry['result_key']}: rebuilt payload does not match manifest")
            continue
        selected_order = expected.get("Selected_Order", {})
        if str(selected_order.get("Sales_Order_ID")) != str(selected["Sales_Order_ID"]):
            failures.append(f"{entry['result_key']}: selected sales order mismatch")
        if str(selected_order.get("Sales_Order_Item")) != str(selected["Sales_Order_Item"]):
            failures.append(f"{entry['result_key']}: selected sales order item mismatch")
        verified = expected.get("Verified_Exceptions", [])
        verified_exception_count += len(verified)
        if not verified:
            failures.append(f"{entry['result_key']}: no verified exception")
        for exception in verified:
            if str(exception.get("Sales_Order_ID")) != str(selected["Sales_Order_ID"]):
                failures.append(f"{entry['result_key']}: cross-order exception detected")
            if str(exception.get("Sales_Order_Item")) != str(selected["Sales_Order_Item"]):
                failures.append(f"{entry['result_key']}: cross-item exception detected")
        primary = expected.get("Primary_Exception") or {}
        if expected.get("Python_Priority") != primary.get("Priority"):
            failures.append(f"{entry['result_key']}: priority mismatch")
        if expected.get("Priority_Rule_ID") != primary.get("Priority_Rule_ID"):
            failures.append(f"{entry['result_key']}: priority rule mismatch")
        completeness = expected.get("Payload_Completeness", {})
        if completeness.get("expected_material_signal_count") != completeness.get("covered_material_signal_count"):
            failures.append(f"{entry['result_key']}: incomplete material-signal coverage")
        encoded = json.dumps(expected, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        payload_hashes.append(hashlib.sha256(encoded).hexdigest())

    try:
        manifest_label = args.manifest.resolve().relative_to(project_root).as_posix()
    except ValueError:
        manifest_label = args.manifest.name

    status = "FAIL" if failures else (
        "PASS" if source_version_matches else "PASS_WITH_PROVENANCE_NOTE"
    )
    report = {
        "status": status,
        "manifest": manifest_label,
        "evaluation_run_id": manifest["evaluation_run_id"],
        "evaluation_call_code_version": manifest["code_version"],
        "current_public_code_version": current_source_version,
        "source_version_matches_manifest": source_version_matches,
        "compatibility_mode": args.compatibility_mode,
        "entry_count": len(entries),
        "scenario_count": len(scenario_counts),
        "entries_per_scenario": dict(sorted(scenario_counts.items())),
        "unique_result_key_count": len(set(result_keys)),
        "exactly_rebuilt_payload_count": len(entries) - sum("rebuilt payload" in item for item in failures),
        "verified_exception_count_in_bounded_payloads": verified_exception_count,
        "unique_payload_hash_count": len(set(payload_hashes)),
        "checks": [
            "evaluation call source fingerprint is retained separately from public code",
            "100 unique order-level results",
            "four results per each of 25 valid workbooks",
            "every payload exactly reproduced from current deterministic analysis",
            "no selected-order or selected-item scope leakage",
            "primary priority and priority-rule identity preserved",
            "material-signal coverage complete before bounded truncation",
        ],
        "failures": failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
