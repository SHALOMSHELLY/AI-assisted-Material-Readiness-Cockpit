"""Opt-in one-call OpenRouter smoke test."""

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.llm_client import LLMConfigurationError, LLMRequestError, configured_model, displayed_cost, generate_explanation
from src.llm_prompt import build_structured_input
from src.shortage_engine import run_shortage_analysis
from src.workbook_reader import read_workbook


def main() -> int:
    parser = argparse.ArgumentParser(description="Run at most one explicitly confirmed live OpenRouter request.")
    parser.add_argument("--confirm-live-api", action="store_true", help="Confirm one real API call may incur cost.")
    args = parser.parse_args()
    if not args.confirm_live_api:
        print("No live API call was made. Add --confirm-live-api only when you intentionally accept one call and possible cost.")
        return 0

    print(f"Model: {configured_model()}")
    print("This smoke test makes at most one API call and never prints the API key.")

    result = run_shortage_analysis(
        read_workbook(ROOT / "test_data" / "sample_workbook.xlsx"), date(2026, 9, 25)
    )
    facts = build_structured_input(result.shortage_results.iloc[0])
    try:
        response = generate_explanation(facts)
    except (LLMConfigurationError, LLMRequestError) as exc:
        status = f"HTTP {exc.status_code}" if exc.status_code is not None else "HTTP status unavailable"
        print(f"{status}; category={exc.category}")
        print(str(exc))
        return 2
    print(f"Model: {response.model}")
    print(f"Generation ID: {response.generation_id or 'N/A'}")
    print(f"Input tokens: {response.input_tokens if response.input_tokens is not None else 'N/A'}")
    print(f"Output tokens: {response.output_tokens if response.output_tokens is not None else 'N/A'}")
    print(f"Total tokens: {response.total_tokens if response.total_tokens is not None else 'N/A'}")
    print(f"Response time: {response.response_time_seconds:.3f}s")
    cost = displayed_cost(response)
    if cost is None:
        print("Cost unavailable")
    else:
        label, value, note = cost
        print(f"{label}: ${value:.8f} USD")
        print(note)
    print(f"Pricing source: {response.pricing_source or 'N/A'}")
    print(f"Pricing as of: {response.pricing_as_of or 'N/A'}")
    print("Live smoke test passed; one API call was made.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
