"""Phase 7 fixed metrics and English evaluation report."""

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from src.phase7_evaluation import RATINGS, matching_calls, validate_ratings


def _rate(count: int, denominator: int) -> float | None:
    return count / denominator * 100 if denominator else None


def build_summary(manifest: dict[str, Any], calls: list[dict[str, Any]], ratings: list[dict[str, Any]]) -> dict[str, Any]:
    validate_ratings(ratings)
    calls = matching_calls(manifest, calls)
    planned_keys = {entry["result_key"] for entry in manifest["entries"] if entry["planned_llm_calls"]}
    histories: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for call in calls:
        histories[call["result_key"]].append(call)
    final_calls = [max(history, key=lambda item: item.get("attempt_number", 0)) for history in histories.values()]
    terminal_keys = set(histories)
    unattempted_keys = planned_keys - terminal_keys
    rated = [row for row in ratings if row.get("human_rating") in RATINGS]
    reviewers = sorted({row.get("reviewer", "").strip() for row in rated if row.get("reviewer", "").strip()})
    review_method = "AI-assisted review" if any("AI" in reviewer for reviewer in reviewers) else "Human review"
    counts = Counter(row["human_rating"] for row in rated)
    denominator = len(rated)
    success = [call for call in final_calls if call.get("success")]
    failed = [call for call in final_calls if not call.get("success")]
    expected_recommendations = sum(len(call.get("parsed_output", {}).get("recommended_actions", [])) for call in success)
    token_fields = {name: sum(call.get(name) or 0 for call in calls) for name in (
        "input_tokens", "output_tokens", "total_tokens"
    )}
    latencies = [call["response_time_seconds"] for call in calls if isinstance(call.get("response_time_seconds"), (int, float))]
    exact = [call["exact_cost_usd"] for call in calls if call.get("exact_cost_usd") is not None]
    estimated = [call["estimated_cost_usd"] for call in calls if call.get("estimated_cost_usd") is not None]
    workbook_costs: dict[str, dict[str, Any]] = defaultdict(lambda: {"call_count": 0, "exact_cost_usd": 0.0, "estimated_cost_usd": 0.0})
    for entry in manifest["entries"]:
        workbook_costs[entry["workbook_name"]]
    for call in calls:
        item = workbook_costs[call["workbook_name"]]
        item["call_count"] += 1
        item["exact_cost_usd"] += call.get("exact_cost_usd") or 0
        item["estimated_cost_usd"] += call.get("estimated_cost_usd") or 0
    blocked = sorted({entry["workbook_name"] for entry in manifest["entries"] if entry["blocked_before_llm"]})
    valid_workbooks = sorted({entry["workbook_name"] for entry in manifest["entries"] if not entry["blocked_before_llm"]})
    ratings_complete = len(ratings) == expected_recommendations and len(rated) == expected_recommendations
    calls_complete = not unattempted_keys and len(terminal_keys) == len(planned_keys)
    return {
        "status": "COMPLETE" if calls_complete and ratings_complete else "INCOMPLETE",
        "completion_policy": "All planned results terminal (success or failure) and every successful recommendation rated",
        "terminal_result_count": len(terminal_keys), "unattempted_result_count": len(unattempted_keys),
        "expected_recommendations_from_successes": expected_recommendations,
        "headline_metric": "Unsupported Recommendation Rate",
        "total_recommendations": len(ratings), "rated_recommendations": denominator,
        "unrated_recommendations": len(ratings) - denominator,
        "review_method": review_method, "reviewers": reviewers,
        "supported_count": counts["Supported"],
        "partially_supported_count": counts["Partially Supported"],
        "unsupported_count": counts["Unsupported"], "contradictory_count": counts["Contradictory"],
        "supported_rate": _rate(counts["Supported"], denominator),
        "partially_supported_rate": _rate(counts["Partially Supported"], denominator),
        "unsupported_recommendation_rate": _rate(counts["Unsupported"], denominator),
        "contradiction_rate": _rate(counts["Contradictory"], denominator),
        "non_fully_supported_rate": _rate(counts["Partially Supported"] + counts["Unsupported"] + counts["Contradictory"], denominator),
        "high_risk_recommendation_rate": _rate(counts["Unsupported"] + counts["Contradictory"], denominator),
        "scenario_count": manifest["scenario_count"], "valid_workbook_count": len(valid_workbooks),
        "evaluation_scope": manifest.get("evaluation_scope", "Representative-order evaluation only."),
        "eligible_order_count": manifest.get("eligible_order_count"),
        "eligible_exception_count": manifest.get("eligible_exception_count"),
        "evaluated_order_count": manifest["planned_llm_calls"],
        "data_error_workbook_count": len(blocked), "data_error_workbooks": blocked,
        "planned_call_count": manifest["planned_llm_calls"], "call_attempt_count": len(calls),
        "successful_call_count": len(success),
        "failed_call_count": len(failed),
        "safe_error_categories": dict(Counter(call.get("safe_error_category") or "unknown" for call in failed)),
        **token_fields,
        "average_total_tokens": token_fields["total_tokens"] / len(calls) if calls else None,
        "min_response_time_seconds": min(latencies) if latencies else None,
        "average_response_time_seconds": sum(latencies) / len(latencies) if latencies else None,
        "max_response_time_seconds": max(latencies) if latencies else None,
        "exact_cost_call_count": len(exact), "exact_cost_total_usd": sum(exact),
        "estimated_cost_call_count": len(estimated), "estimated_cost_total_usd": sum(estimated),
        "average_exact_cost_per_success": sum(exact) / len(exact) if exact else None,
        "average_estimated_cost_per_success": sum(estimated) / len(estimated) if estimated else None,
        "average_exact_cost_per_valid_workbook": sum(exact) / len(valid_workbooks) if valid_workbooks else None,
        "average_estimated_cost_per_valid_workbook": sum(estimated) / len(valid_workbooks) if valid_workbooks else None,
        "average_exact_cost_per_all_scenarios": sum(exact) / manifest["scenario_count"] if manifest["scenario_count"] else None,
        "average_estimated_cost_per_all_scenarios": sum(estimated) / manifest["scenario_count"] if manifest["scenario_count"] else None,
        "workbooks": dict(sorted(workbook_costs.items())),
        "model": manifest["model"], "prompt_version": manifest["prompt_version"],
        "schema_version": manifest["schema_version"], "analysis_date": manifest["created_for_analysis_date"],
        "pricing_as_of": manifest["pricing_as_of"], "pricing_source": manifest["pricing_source"],
    }


def _display_rate(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f}%"


def write_report(summary: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "evaluation_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    with (output_dir / "evaluation_summary.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle); writer.writerow(["metric", "value"])
        for key, value in summary.items():
            writer.writerow([key, json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value])
    denominator = summary["rated_recommendations"]
    report = f"""# Phase 7 LLM Evaluation Report

## Evaluation Objective

**Unsupported Recommendation Rate: {_display_rate(summary['unsupported_recommendation_rate'])} ({summary['unsupported_count']}/{denominator}).**

This is not an overall correctness rate. The Fully Supported Rate is {_display_rate(summary['supported_rate'])}; the Non-Fully-Supported Rate is {_display_rate(summary['non_fully_supported_rate'])}.

Status: **{summary['status']}**. Total recommendations: {summary['total_recommendations']}; rated: {denominator}; unrated: {summary['unrated_recommendations']}. A report with unrated recommendations is not final.

## Fixed Dataset

The evaluation uses {summary['scenario_count']} fixed synthetic SAP-style workbooks, not official SAP production exports. Valid workbooks: {summary['valid_workbook_count']}; Data Error workbooks: {summary['data_error_workbook_count']}; planned calls: {summary['planned_call_count']}.

Evaluation scope: {summary['evaluation_scope']} Eligible orders: {summary['eligible_order_count']}; evaluated orders: {summary['evaluated_order_count']}; eligible exceptions: {summary['eligible_exception_count']}.

## Model and Configuration

- Model: `{summary['model']}`
- Prompt: `{summary['prompt_version']}`
- Schema: `{summary['schema_version']}`
- Analysis date: `{summary['analysis_date']}`
- Pricing snapshot: `{summary['pricing_as_of']}`

## Evaluation Procedure

Validation and deterministic Python analysis run first; Data Errors block LLM calls. Each selected result receives at most one formal generation with no automatic retry. Each recommended action is rated separately, and deterministic flags are review aids only. Review method: {summary['review_method']} ({', '.join(summary['reviewers']) or 'Not recorded'}).

## Recommendation Metrics

- Supported Rate: {_display_rate(summary['supported_rate'])} ({summary['supported_count']}/{denominator})
- Partially Supported Rate: {_display_rate(summary['partially_supported_rate'])} ({summary['partially_supported_count']}/{denominator})
- Unsupported Recommendation Rate: {_display_rate(summary['unsupported_recommendation_rate'])} ({summary['unsupported_count']}/{denominator})
- Contradiction Rate: {_display_rate(summary['contradiction_rate'])} ({summary['contradictory_count']}/{denominator})
- Non-Fully-Supported Rate: {_display_rate(summary['non_fully_supported_rate'])}
- High-Risk Recommendation Rate: {_display_rate(summary['high_risk_recommendation_rate'])}

## Cost

- Exact API cost: `${summary['exact_cost_total_usd']:.8f}` across {summary['exact_cost_call_count']} calls
- Estimated cost: `${summary['estimated_cost_total_usd']:.8f}` across {summary['estimated_cost_call_count']} calls
- Exact cost per valid workbook: `${summary['average_exact_cost_per_valid_workbook']:.8f}`
- Exact cost per planned workbook: `${summary['average_exact_cost_per_all_scenarios']:.8f}`
- Deterministic Python calculation cost: `$0`

Exact and estimated totals are kept separate.

## Tokens and Latency

- Successful calls: {summary['successful_call_count']}
- Failed calls: {summary['failed_call_count']}
- Input tokens: {summary['input_tokens']}
- Output tokens: {summary['output_tokens']}
- Total tokens: {summary['total_tokens']}
- Average tokens per call: {summary['average_total_tokens']}
- Minimum/average/maximum latency: {summary['min_response_time_seconds']} / {summary['average_response_time_seconds']} / {summary['max_response_time_seconds']} seconds

Safe error categories: `{json.dumps(summary['safe_error_categories'], ensure_ascii=False)}`.

Data Error workbooks: `{', '.join(summary['data_error_workbooks']) or 'None'}`.

## Limitations

The sample is synthetic and the review is AI-assisted rather than independent human-only review. One generation model and one reviewing system do not represent all models. Provider versions and prices may change, and free text cannot be guaranteed hallucination-free.

The system does not modify SAP, create purchase orders, send messages, or execute recommendations. Every recommendation requires planner review.
"""
    (output_dir / "phase7_evaluation_report.md").write_text(report, encoding="utf-8")
