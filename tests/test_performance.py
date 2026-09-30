from datetime import date
from pathlib import Path
import time

import pytest

from src.analysis_service import analyze_workbook_content


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.performance
@pytest.mark.parametrize("scenario", ["L01", "L08"])
def test_large_analysis_completes_with_wide_guardrail(scenario):
    path = next((ROOT / "data/expanded_scenarios/generated/large").glob(f"{scenario}.xlsx"))
    started = time.perf_counter()
    analyzed = analyze_workbook_content(path.read_bytes(), date(2026, 9, 25))
    assert analyzed.result.validation_report.is_valid
    assert time.perf_counter() - started < 30
