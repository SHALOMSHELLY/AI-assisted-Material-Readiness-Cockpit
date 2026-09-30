"""Safe Phase 7 command-line workflow."""

import argparse
import csv
import json
from pathlib import Path

from src.phase7_evaluation import (
    build_manifest, execute_calls, generate_ratings, load_calls, matching_calls, pending_entries,
    revalidate_failed_outputs, validate_ratings, write_manifest,
)
from src.phase7_report import build_summary, write_report


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "results" / "phase7_stratified_100"
MANIFEST_PATH = OUTPUT / "evaluation_manifest.json"
LEDGER_PATH = OUTPUT / "llm_calls.jsonl"
RATINGS_PATH = OUTPUT / "recommendation_ratings.csv"


def load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        raise ValueError("Run prepare first to create the evaluation manifest.")
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def show_status(manifest: dict, calls: list[dict]) -> None:
    calls = matching_calls(manifest, calls)
    completed = {call["result_key"] for call in calls if call.get("success")}
    failed = {call["result_key"] for call in calls if not call.get("success")}
    print(f"Model: {manifest['model']}")
    print(f"Prompt: {manifest['prompt_version']}")
    print(f"Schema: {manifest['schema_version']}")
    print(f"Planned calls: {manifest['planned_llm_calls']}")
    print(f"Completed results: {len(completed)}")
    print(f"Failed results: {len(failed - completed)}")
    print(f"Unattempted: {len(pending_entries(manifest, calls, resume=True, retry_failed=False))}")
    print(f"Pricing snapshot: {manifest['pricing_as_of']} {manifest['estimated_cost_range_usd']} USD")
    print("The estimate is not a final bill. Each result is called at most once by default.")


def read_ratings() -> list[dict]:
    if not RATINGS_PATH.exists():
        return []
    with RATINGS_PATH.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 7 fixed-dataset LLM evaluation")
    parser.add_argument(
        "command",
        choices=["prepare", "status", "run", "resume", "revalidate", "ratings", "report"],
    )
    parser.add_argument("--confirm-live-api", action="store_true")
    parser.add_argument("--max-calls", type=int)
    parser.add_argument("--retry-failed", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            manifest = build_manifest(ROOT, include_expanded_medium=True)
            write_manifest(manifest, OUTPUT)
            print(
                f"Prepared {manifest['scenario_count']} scenarios; planned calls: "
                f"{manifest['planned_llm_calls']}."
            )
            print(f"Estimated cost range: {manifest['estimated_cost_range_usd']} USD")
            print("No API key was read and no API call was made.")
            return 0
        manifest = load_manifest(); calls = load_calls(LEDGER_PATH)
        if args.command == "status":
            show_status(manifest, calls); print("No API call was made.")
            return 0
        if args.command in {"run", "resume"}:
            show_status(manifest, calls)
            if not args.confirm_live_api:
                print("No live API call was made. Add --confirm-live-api only when accepting real cost.")
                return 0
            pending = pending_entries(manifest, calls, resume=args.command == "resume", retry_failed=args.retry_failed)
            maximum = len(pending) if args.max_calls is None else args.max_calls
            if maximum > len(pending):
                raise ValueError("--max-calls exceeds the number of pending results.")
            print(f"Maximum live calls: {maximum}. Automatic retries are disabled.")
            count = execute_calls(manifest, LEDGER_PATH, max_calls=maximum,
                                  resume=args.command == "resume", retry_failed=args.retry_failed)
            print(f"Recorded attempts: {count}")
            return 0
        if args.command == "revalidate":
            count = revalidate_failed_outputs(manifest, LEDGER_PATH)
            print(f"Locally revalidated results: {count}. No API call was made.")
            return 0
        if args.command == "ratings":
            rows = generate_ratings(calls, RATINGS_PATH)
            print(f"Rating rows: {len(rows)}. Existing human ratings were preserved.")
            print("No API call was made.")
            return 0
        ratings = read_ratings(); validate_ratings(ratings)
        summary = build_summary(manifest, calls, ratings); write_report(summary, OUTPUT)
        print(f"Report status: {summary['status']}")
        print(f"Rated: {summary['rated_recommendations']}/{summary['total_recommendations']}")
        print("No API call was made.")
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"Operation not completed: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
