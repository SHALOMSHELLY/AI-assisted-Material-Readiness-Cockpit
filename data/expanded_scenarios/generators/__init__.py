"""Deterministic expanded shortage-planning scenario definitions."""

from .common import ANALYSIS_DATE
from .large_scenarios import LARGE_SCENARIOS
from .medium_scenarios import MEDIUM_SCENARIOS
from .small_scenarios import SMALL_SCENARIOS

ALL_SCENARIOS = {**SMALL_SCENARIOS, **MEDIUM_SCENARIOS, **LARGE_SCENARIOS}

__all__ = ["ALL_SCENARIOS", "ANALYSIS_DATE", "SMALL_SCENARIOS", "LARGE_SCENARIOS", "MEDIUM_SCENARIOS"]
