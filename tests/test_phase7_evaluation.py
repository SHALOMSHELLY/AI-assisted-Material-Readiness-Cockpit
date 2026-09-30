"""Offline Phase 7 evaluation tests."""

import csv
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from src.llm_client import LLMRequestError, LLMResult
from src.phase7_evaluation import (
    RATINGS, append_call, build_manifest, execute_calls, generate_ratings,
    load_calls, pending_entries, revalidate_failed_outputs, validate_ratings, write_manifest,
)
from src.phase7_report import build_summary, write_report


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def manifest():
    return build_manifest(ROOT)


def planned(manifest):
    return [entry for entry in manifest["entries"] if entry["planned_llm_calls"]]


def parsed_output(facts):
    return {
        "priority_summary": " / Summary", "explanation": " / Explanation",
        "exception_reviews": [],
        "python_priority": facts["Python_Priority"], "priority_rule_id": facts["Priority_Rule_ID"],
        "recommended_actions": [{
            "action_type": "Escalate to procurement", "action": " / Escalate for human review",
            "evidence": [{"exception_id": None, "field": "Shortage_Quantity", "value": facts["Shortage_Quantity"], "unit": facts["Quantity_Unit"]}],
            "requires_human_approval": True, "execution_status": "NOT_EXECUTED",
        }],
        "missing_information_codes": [],
    }


def successful_call(manifest, entry, *, cost=0.001):
    facts = entry["structured_input"]
    return {
        "evaluation_run_id": manifest["evaluation_run_id"], "scenario_id": entry["scenario_id"],
        "workbook_name": entry["workbook_name"], "workbook_sha256": entry["workbook_sha256"],
        "analysis_date": manifest["created_for_analysis_date"], "result_key": entry["result_key"],
        "model": manifest["model"], "prompt_version": manifest["prompt_version"],
        "schema_version": manifest["schema_version"],
        "attempt_number": 1, "success": True, "safe_error_category": None,
        "structured_validation_passed": True, "input_tokens": 100, "output_tokens": 20,
        "total_tokens": 120, "response_time_seconds": 1.5, "exact_cost_usd": cost,
        "estimated_cost_usd": 0.000072, "pricing_source": manifest["pricing_source"],
        "pricing_as_of": manifest["pricing_as_of"], "structured_input": facts,
        "parsed_output": parsed_output(facts), "raw_output": "{}", "execution_claim_detected": False,
    }


def test_manifest_has_fixed_scenario_order(manifest):
    ids = [entry["scenario_id"] for entry in manifest["entries"]]
    assert ids == sorted(ids)


def test_manifest_contains_all_25_scenarios(manifest):
    assert manifest["scenario_count"] == 25
    assert len({entry["scenario_id"] for entry in manifest["entries"]}) == 25


def test_manifest_has_no_data_error_workbooks(manifest):
    assert not {entry["scenario_id"] for entry in manifest["entries"] if entry["blocked_before_llm"]}


def test_data_error_entries_plan_zero_calls(manifest):
    assert all(entry["planned_llm_calls"] == 0 for entry in manifest["entries"] if entry["blocked_before_llm"])


def test_valid_result_rows_plan_one_call(manifest):
    assert all(entry["planned_llm_calls"] == 1 for entry in planned(manifest))


def test_manifest_has_four_calls_per_formal_workbook(manifest):
    assert len(planned(manifest)) == manifest["planned_llm_calls"] == 100
    counts = {}
    for entry in planned(manifest):
        counts[entry["scenario_id"]] = counts.get(entry["scenario_id"], 0) + 1
    assert set(counts.values()) == {4}


def test_manifest_uses_ui_order_payload_and_excludes_workflow_state(manifest):
    for entry in planned(manifest):
        payload = entry["structured_input"]
        assert {
            key: payload["Selected_Order"][key]
            for key in ("Sales_Order_ID", "Sales_Order_Item")
        } == entry["selected_order"]
        assert payload["Verified_Exceptions"]
        for exception in payload["Verified_Exceptions"]:
            assert "Workflow_Status" not in exception
            assert exception["Suggested_Responsible_Function"]
            assert exception["Python_Priority"] == exception["Priority"]


def test_manifest_configuration_is_fixed(manifest):
    assert manifest["model"] == "openai/gpt-4.1-mini"
    assert manifest["temperature"] == 0 and manifest["max_tokens"] == 6000
    assert manifest["created_for_analysis_date"] == "2026-09-25"
    assert manifest["sampling_seed"] == 6201
    assert manifest["samples_per_workbook"] == 4


def test_manifest_estimate_is_labeled_not_final(manifest):
    assert manifest["estimated_cost_range_usd"][0] > 0
    assert "not a final bill" in manifest["estimated_cost_note"]


def test_manifest_repeat_is_stable(manifest):
    again = build_manifest(ROOT)
    assert again["evaluation_run_id"] == manifest["evaluation_run_id"]
    assert [(e["scenario_id"], e["result_key"]) for e in again["entries"]] == [(e["scenario_id"], e["result_key"]) for e in manifest["entries"]]
    assert [e["sampling_stratum"] for e in planned(again)] == [
        e["sampling_stratum"] for e in planned(manifest)
    ]


def test_manifest_json_and_csv_are_written(manifest, tmp_path):
    write_manifest(manifest, tmp_path)
    assert (tmp_path / "evaluation_manifest.json").exists()
    assert (tmp_path / "evaluation_manifest.csv").read_bytes().startswith(b"\xef\xbb\xbf")


def test_successful_result_is_never_pending(manifest):
    entry = planned(manifest)[0]
    assert entry not in pending_entries(manifest, [successful_call(manifest, entry)], resume=True, retry_failed=True)


def test_failed_result_is_not_retried_by_default(manifest):
    entry = planned(manifest)[0]
    failed = {**successful_call(manifest, entry), "success": False}
    assert entry not in pending_entries(manifest, [failed], resume=True, retry_failed=False)


def test_retry_failed_explicitly_requeues(manifest):
    entry = planned(manifest)[0]
    failed = {**successful_call(manifest, entry), "success": False}
    assert entry in pending_entries(manifest, [failed], resume=True, retry_failed=True)


def test_resume_only_returns_unattempted(manifest):
    first = planned(manifest)[0]
    pending = pending_entries(manifest, [successful_call(manifest, first)], resume=True, retry_failed=False)
    assert first not in pending and len(pending) == 99


def test_max_calls_cannot_exceed_pending(manifest, tmp_path):
    with pytest.raises(ValueError):
        execute_calls(manifest, tmp_path / "calls.jsonl", max_calls=101, generator=lambda facts: None)


def test_call_is_appended_immediately_and_contains_no_key(manifest, tmp_path):
    path = tmp_path / "calls.jsonl"
    append_call(path, {"result_key": "x", "success": True})
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1
    assert "OPENROUTER_API_KEY" not in path.read_text(encoding="utf-8")


def test_execute_records_tokens_cost_and_attempt(manifest, tmp_path):
    path = tmp_path / "calls.jsonl"
    def fake(facts):
        return LLMResult(parsed_output(facts), "{}", manifest["model"], 100, 20, 120, 1.2,
                         "gen-test", 0.001, 0.000072, manifest["pricing_source"], manifest["pricing_as_of"])
    assert execute_calls(manifest, path, max_calls=1, generator=fake) == 1
    record = load_calls(path)[0]
    assert record["attempt_number"] == 1 and record["total_tokens"] == 120
    assert record["exact_cost_usd"] == 0.001 and record["estimated_cost_usd"] == 0.000072


def test_failed_call_is_recorded_without_automatic_retry(manifest, tmp_path):
    path = tmp_path / "calls.jsonl"
    def fail(_): raise LLMRequestError("safe", category="request")
    execute_calls(manifest, path, max_calls=1, generator=fail)
    record = load_calls(path)[0]
    assert record["success"] is False and record["safe_error_category"] == "request"
    assert record["raw_output"] is None


def test_explicit_retry_creates_second_attempt(manifest, tmp_path):
    path = tmp_path / "calls.jsonl"
    def fail(_): raise LLMRequestError("safe", category="request")
    execute_calls(manifest, path, max_calls=1, generator=fail)
    execute_calls(manifest, path, max_calls=1, resume=True, retry_failed=True, generator=fail)
    assert [row["attempt_number"] for row in load_calls(path)] == [1, 2]


def test_local_revalidation_is_append_only_and_zero_cost(manifest, tmp_path):
    path = tmp_path / "calls.jsonl"
    entry = planned(manifest)[0]
    failed = successful_call(manifest, entry)
    failed.update({
        "success": False,
        "safe_error_category": "structured_validation",
        "structured_validation_passed": False,
        "parsed_output": None,
        "raw_output": json.dumps({
            "priority_summary": "Verified exceptions require review.",
            "explanation": "The verified facts require human review.",
            "python_priority": "WRONG",
            "priority_rule_id": "WRONG",
            "exception_reviews": [],
            "recommended_actions": [],
            "missing_information_codes": [],
        }),
    })
    append_call(path, failed)
    assert revalidate_failed_outputs(manifest, path) == 1
    first, second = load_calls(path)
    assert first["success"] is False and second["success"] is True
    assert second["attempt_number"] == 2
    assert second["exact_cost_usd"] is None and second["total_tokens"] is None
    assert second["revalidated_from_attempt"] == 1


def test_rating_table_has_one_row_per_action(manifest, tmp_path):
    call = successful_call(manifest, planned(manifest)[0])
    rows = generate_ratings([call], tmp_path / "ratings.csv")
    assert len(rows) == 1 and rows[0]["action_index"] == 1


def test_rating_table_uses_latest_attempt_only(manifest, tmp_path):
    first = successful_call(manifest, planned(manifest)[0])
    retry = {**first, "attempt_number": 2}
    rows = generate_ratings([first, retry], tmp_path / "ratings.csv")
    assert len(rows) == 1


def test_rating_key_is_stable(manifest, tmp_path):
    call = successful_call(manifest, planned(manifest)[0])
    first = generate_ratings([call], tmp_path / "ratings.csv")[0]["rating_key"]
    second = generate_ratings([call], tmp_path / "ratings.csv")[0]["rating_key"]
    assert first == second


def test_rating_csv_is_utf8_sig(manifest, tmp_path):
    generate_ratings([successful_call(manifest, planned(manifest)[0])], tmp_path / "ratings.csv")
    assert (tmp_path / "ratings.csv").read_bytes().startswith(b"\xef\xbb\xbf")


def test_regeneration_preserves_human_rating(manifest, tmp_path):
    path = tmp_path / "ratings.csv"; call = successful_call(manifest, planned(manifest)[0])
    generate_ratings([call], path)
    with path.open(encoding="utf-8-sig", newline="") as handle: rows = list(csv.DictReader(handle))
    rows[0].update(human_rating="Supported", human_reason="checked", reviewer="teacher", reviewed_at="2026-09-25")
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0]); writer.writeheader(); writer.writerows(rows)
    regenerated = generate_ratings([call], path)[0]
    assert regenerated["human_rating"] == "Supported" and regenerated["reviewer"] == "teacher"


def test_illegal_rating_is_rejected():
    with pytest.raises(ValueError): validate_ratings([{"human_rating": "Good"}])


def test_all_four_rating_values_are_valid():
    validate_ratings([{"human_rating": value} for value in RATINGS])


def test_unrated_summary_is_incomplete(manifest):
    summary = build_summary(manifest, [], [{"human_rating": ""}])
    assert summary["status"] == "INCOMPLETE" and summary["unrated_recommendations"] == 1


def test_fully_rated_partial_run_remains_incomplete(manifest):
    summary = build_summary(manifest, [], [{"human_rating": "Supported"}])
    assert summary["status"] == "INCOMPLETE"


def test_complete_requires_all_terminal_results_and_all_success_actions_rated(manifest, tmp_path):
    calls = [successful_call(manifest, entry) for entry in planned(manifest)]
    ratings = generate_ratings(calls, tmp_path / "ratings.csv")
    for row in ratings: row["human_rating"] = "Supported"
    summary = build_summary(manifest, calls, ratings)
    assert summary["status"] == "COMPLETE"
    assert summary["terminal_result_count"] == 100
    assert summary["unattempted_result_count"] == 0


def test_zero_denominator_is_safe_and_incomplete(manifest):
    summary = build_summary(manifest, [], [])
    assert summary["unsupported_recommendation_rate"] is None
    assert summary["status"] == "INCOMPLETE"


def test_rating_formulas_keep_categories_separate(manifest):
    rows = [{"human_rating": value} for value in ["Supported", "Partially Supported", "Unsupported", "Contradictory"]]
    summary = build_summary(manifest, [], rows)
    assert summary["supported_rate"] == 25
    assert summary["partially_supported_rate"] == 25
    assert summary["unsupported_recommendation_rate"] == 25
    assert summary["contradiction_rate"] == 25
    assert summary["non_fully_supported_rate"] == 75
    assert summary["high_risk_recommendation_rate"] == 50


def test_costs_and_tokens_are_summarized_without_mixing(manifest):
    calls = [successful_call(manifest, planned(manifest)[0], cost=0.001), successful_call(manifest, planned(manifest)[1], cost=0.002)]
    summary = build_summary(manifest, calls, [])
    assert summary["exact_cost_total_usd"] == pytest.approx(0.003)
    assert summary["estimated_cost_total_usd"] == pytest.approx(0.000144)
    assert summary["total_tokens"] == 240


def test_formal_workbooks_are_valid_and_have_no_calls_without_execution(manifest):
    summary = build_summary(manifest, [], [])
    assert summary["data_error_workbook_count"] == 0
    assert all(item["call_count"] == 0 for item in summary["workbooks"].values())


def test_per_workbook_call_count_and_cost(manifest):
    entries = [entry for entry in planned(manifest) if entry["scenario_id"] == "S01"]
    summary = build_summary(manifest, [successful_call(manifest, entry) for entry in entries], [])
    assert summary["workbooks"]["S01.xlsx"]["call_count"] == 4
    assert summary["workbooks"]["S01.xlsx"]["exact_cost_usd"] == pytest.approx(0.004)


def test_report_contains_required_configuration(manifest, tmp_path):
    summary = build_summary(manifest, [], [])
    write_report(summary, tmp_path)
    text = (tmp_path / "phase7_evaluation_report.md").read_text(encoding="utf-8")
    assert manifest["model"] in text and manifest["prompt_version"] in text
    assert manifest["schema_version"] in text and manifest["pricing_as_of"] in text


@pytest.mark.parametrize("command", ["run", "resume"])
def test_live_commands_without_confirmation_make_no_call(command, tmp_path):
    completed = subprocess.run([sys.executable, str(ROOT / "evaluate_phase7.py"), command], cwd=tmp_path,
                               capture_output=True, text=True, timeout=10, check=False)
    assert completed.returncode == 2 or "No live API call" in completed.stdout


def test_source_contains_no_api_key_value():
    text = (ROOT / "src" / "phase7_evaluation.py").read_text(encoding="utf-8")
    assert "sk-or-" not in text and "Authorization" not in text


def test_structured_validation_error_category_is_distinct():
    error = LLMRequestError(" AI output is not valid JSON.")
    assert error.category == "structured_validation"


def test_local_safety_error_category_is_distinct():
    error = LLMRequestError(" Evidence value does not match Python facts.")
    assert error.category == "local_safety_validation"


def test_old_run_or_changed_workbook_call_is_not_reused(manifest):
    entry = planned(manifest)[0]
    call = successful_call(manifest, entry)
    call["evaluation_run_id"] = "old-run"
    assert entry in pending_entries(manifest, [call], resume=True, retry_failed=False)
    call = successful_call(manifest, entry); call["workbook_sha256"] = "changed"
    assert entry in pending_entries(manifest, [call], resume=True, retry_failed=False)


def test_changed_structured_input_or_config_call_is_not_reused(manifest):
    entry = planned(manifest)[0]
    call = successful_call(manifest, entry); call["structured_input"] = {"different": True}
    assert entry in pending_entries(manifest, [call], resume=True, retry_failed=False)
    call = successful_call(manifest, entry); call["schema_version"] = "old-schema"
    assert entry in pending_entries(manifest, [call], resume=True, retry_failed=False)


def test_prepare_refuses_overwrite_when_different_run_has_ledger(manifest, tmp_path):
    write_manifest(manifest, tmp_path)
    append_call(tmp_path / "llm_calls.jsonl", {"evaluation_run_id": manifest["evaluation_run_id"]})
    changed = deepcopy(manifest); changed["evaluation_run_id"] = "different-run"
    with pytest.raises(ValueError, match="archive"):
        write_manifest(changed, tmp_path)


def test_code_version_is_source_hash(manifest):
    assert manifest["code_version"].startswith("source-sha256:")
    assert len(manifest["code_version"].split(":", 1)[1]) == 64


def test_failed_paid_response_metadata_is_preserved(manifest, tmp_path):
    path = tmp_path / "calls.jsonl"
    def fail(_):
        raise LLMRequestError(
            "invalid output", category="structured_validation",
            response_metadata={
                "model": manifest["model"], "generation_id": "gen-paid",
                "input_tokens": 100, "output_tokens": 20, "total_tokens": 120,
                "response_time_seconds": 1.1, "exact_cost_usd": 0.001,
                "estimated_cost_usd": 0.000072, "pricing_source": manifest["pricing_source"],
                "pricing_as_of": manifest["pricing_as_of"], "raw_output": "bad-json",
            },
        )
    execute_calls(manifest, path, max_calls=1, generator=fail)
    record = load_calls(path)[0]
    assert record["success"] is False and record["exact_cost_usd"] == 0.001
    assert record["total_tokens"] == 120 and record["generation_id"] == "gen-paid"


def test_workbook_summary_always_contains_all_25_workbooks(manifest):
    summary = build_summary(manifest, [], [])
    assert len(summary["workbooks"]) == 25
    assert all(item["call_count"] == 0 for item in summary["workbooks"].values())
