"""Apply a reproducible AI-assisted review to the Phase 7 rating template.

This does not claim independent human review.  It validates every action
against the deterministic quantities and evidence already recorded in the
formal ledger, then labels the reviewer explicitly.
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "results" / "phase7_stratified_100"
RATINGS = OUTPUT / "recommendation_ratings.csv"
LEDGER = OUTPUT / "llm_calls.jsonl"
REVIEW = OUTPUT / "ai_assisted_review.json"
REVIEWER = "Codex (AI-assisted review)"


def rate(row: dict[str, str]) -> tuple[str, str]:
    evidence = json.loads(row["evidence_json"])
    evidence_by_field: dict[str, list[object]] = {}
    for item in evidence:
        evidence_by_field.setdefault(item["field"], []).append(item["value"])
    action_type = row["action_type"]
    action_text = row["action_text"]

    if row["suggested_rule_flags"].strip():
        return "Unsupported", f"Automated review flags were present: {row['suggested_rule_flags']}."
    if action_type == "Escalate to procurement":
        shortages = [float(value) for value in evidence_by_field.get("Shortage_Quantity", [])]
        if not shortages or any(value <= 0 for value in shortages):
            return "Contradictory", "Procurement escalation is not supported by an exact positive shortage citation."
        base_reason = "The advisory procurement escalation cites positive deterministic shortage evidence and requests human investigation only."
    elif action_type == "Request missing data":
        incoming = [
            float(value)
            for field in ("Late_Incoming_Quantity", "Overdue_Incoming_Quantity")
            for value in evidence_by_field.get(field, [])
        ]
        has_supply_reference = bool(
            incoming
            or evidence_by_field.get("Next_Receipt_Date")
            or evidence_by_field.get("Material_ID")
        )
        if not has_supply_reference or any(value <= 0 for value in incoming):
            return "Unsupported", "The missing-data request lacks verified supply-exception evidence."
        base_reason = "The request is supported by positive late/overdue supply evidence and asks for supplier confirmation or cross-order review rather than claiming an outcome."
    elif action_type == "Escalate to production planning":
        planning_fields = {
            "Production_Order_ID", "Planned_End_Date", "Requested_Delivery_Date",
            "Planned_Start_Date", "Days_After_Requested_Delivery", "Analysis_Date",
        }
        if not planning_fields.intersection(evidence_by_field):
            return "Unsupported", "The production-planning escalation lacks verified planning evidence."
        base_reason = "The advisory escalation cites a verified planning exception and requests human production-planning review only."
    else:
        return "Unsupported", "The action type is outside the action types covered by this AI-assisted review rubric."

    gaps: list[str] = []
    if "critical" in action_text.lower() and "Critical" not in evidence_by_field.get("Python_Priority", []):
        gaps.append("the Critical label is not cited in action evidence")
    if re.search(r"\bzero shortages?\b", action_text, re.IGNORECASE):
        if 0 not in evidence_by_field.get("Shortage_Quantity", []):
            gaps.append("the zero-shortage claim is not cited in action evidence")
    cited_values = {str(value) for values in evidence_by_field.values() for value in values}
    for value, unit in re.findall(r"\b(\d+(?:\.\d+)?)\s+(EA|KG|L|M)\b", action_text):
        normalized = str(float(value))
        if value not in cited_values and normalized not in cited_values:
            gaps.append(f"the stated quantity {value} {unit} is not cited in action evidence")
    for value in re.findall(r"\b\d{4}-\d{2}-\d{2}\b", action_text):
        if value not in cited_values:
            gaps.append(f"the stated date {value} is not cited in action evidence")
    if gaps:
        return "Partially Supported", base_reason + " However, " + "; ".join(dict.fromkeys(gaps)) + "."
    return "Supported", base_reason


def main() -> int:
    with RATINGS.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fields = reader.fieldnames
    if not rows or not fields:
        raise ValueError("The Phase 7 rating template is missing or empty.")
    for row in rows:
        row["human_rating"], row["human_reason"] = rate(row)
        row["reviewer"] = REVIEWER
        row["reviewed_at"] = date.today().isoformat()
    with RATINGS.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["human_rating"]] = counts.get(row["human_rating"], 0) + 1
    calls = [json.loads(line) for line in LEDGER.read_text(encoding="utf-8").splitlines() if line.strip()]
    successful = [call for call in calls if call.get("success")]
    narrative_ratings = []
    for call in successful:
        parsed = call.get("parsed_output") or {}
        checks_passed = all((
            call.get("structured_validation_passed") is True,
            call.get("python_priority_consistent") is True,
            call.get("priority_rule_id_consistent") is True,
            call.get("obvious_numeric_contradiction") is False,
            call.get("execution_claim_detected") is False,
            call.get("missing_information_codes_valid") is True,
            isinstance(parsed.get("priority_summary"), str) and bool(parsed["priority_summary"].strip()),
            isinstance(parsed.get("explanation"), str) and bool(parsed["explanation"].strip()),
        ))
        narrative_ratings.append({
            "result_key": call["result_key"],
            "rating": "Supported" if checks_passed else "Unsupported",
            "reason": (
                "The narrative passed the strict schema, priority, rule, numeric-contradiction, "
                "execution-claim, and missing-information checks against the deterministic fact package."
                if checks_passed else
                "One or more required narrative validation checks did not pass."
            ),
            "reviewer": REVIEWER,
            "reviewed_at": date.today().isoformat(),
        })
    review = {
        "review_method": "AI-assisted review; not independent human review",
        "reviewer": REVIEWER,
        "narrative_ratings": narrative_ratings,
        "action_ratings": [
            {
                "result_key": row["result_key"], "action_index": row["action_index"],
                "rating": row["human_rating"], "reason": row["human_reason"],
                "reviewer": row["reviewer"], "reviewed_at": row["reviewed_at"],
            }
            for row in rows
        ],
        "summary": {
            "successful_results_reviewed": len(narrative_ratings),
            "narrative_rating_counts": dict(Counter(item["rating"] for item in narrative_ratings)),
            "actions_reviewed": len(rows),
            "action_rating_counts": counts,
        },
    }
    REVIEW.write_text(json.dumps(review, indent=2), encoding="utf-8")
    print(json.dumps({"reviewer": REVIEWER, "rated": len(rows), "counts": counts,
                      "narratives": len(narrative_ratings)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
