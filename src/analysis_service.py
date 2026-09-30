"""Single-pass deterministic workbook analysis shared by UI and evaluations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from hashlib import sha256
from io import BytesIO

import pandas as pd

from src.exception_engine import build_exception_register
from src.order_summary import build_order_summary
from src.shortage_engine import AnalysisResult, run_shortage_analysis
from src.validators import validate_workbook
from src.workbook_reader import read_workbook


ENGINE_VERSION = "deterministic-engine-v3-order-risk-completeness"


@dataclass
class DeterministicAnalysis:
    workbook_sha256: str
    sheets: dict[str, pd.DataFrame]
    result: AnalysisResult
    exceptions: pd.DataFrame
    order_summary: pd.DataFrame


def analysis_cache_key(content: bytes, analysis_date: date) -> tuple[str, str, str]:
    return sha256(content).hexdigest(), analysis_date.isoformat(), ENGINE_VERSION


@lru_cache(maxsize=8)
def _analyze_cached(content: bytes, analysis_date_iso: str, engine_version: str) -> DeterministicAnalysis:
    analysis_date = date.fromisoformat(analysis_date_iso)
    digest, _, _ = analysis_cache_key(content, analysis_date)
    sheets = read_workbook(BytesIO(content))
    report = validate_workbook(sheets, analysis_date)
    result = run_shortage_analysis(sheets, analysis_date, validation_report=report)
    exceptions = build_exception_register(sheets, result, analysis_date)
    return DeterministicAnalysis(
        digest, sheets, result, exceptions,
        build_order_summary(exceptions, sheets["Orders"]),
    )


def analyze_workbook_content(content: bytes, analysis_date: date) -> DeterministicAnalysis:
    """Analyze once per workbook hash/date/version in the current process."""
    return _analyze_cached(content, analysis_date.isoformat(), ENGINE_VERSION)
