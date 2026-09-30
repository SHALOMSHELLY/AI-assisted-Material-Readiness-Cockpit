"""Formal 25-workbook dataset and independent-oracle acceptance tests."""
from __future__ import annotations
from collections import Counter
from datetime import date
import json
from pathlib import Path
import pytest

pytestmark = pytest.mark.formal_oracle

from data.expanded_scenarios.generators import ALL_SCENARIOS
from data.expanded_scenarios.generators.expected_oracle import build_full_expected
from src.shortage_engine import run_shortage_analysis
from src.validators import REQUIRED_SHEETS, validate_workbook
from src.workbook_reader import read_workbook

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "expanded_scenarios"
ANALYSIS_DATE = date(2026, 9, 25)

def workbook_path(sid):
    scenario = ALL_SCENARIOS[sid]
    return DATA / "generated" / scenario.category / f"{sid}.xlsx"

def test_formal_set_is_exactly_9_8_8_and_all_valid():
    assert len(ALL_SCENARIOS) == 25
    assert Counter(s.category for s in ALL_SCENARIOS.values()) == {"small": 9, "medium": 8, "large": 8}
    for sid in sorted(ALL_SCENARIOS):
        sheets = read_workbook(workbook_path(sid))
        assert set(REQUIRED_SHEETS) <= set(sheets)
        assert validate_workbook(sheets, ANALYSIS_DATE).is_valid, sid

@pytest.mark.parametrize("sid", sorted(ALL_SCENARIOS))
def test_workbook_matches_independent_shortage_oracle(sid):
    actual = run_shortage_analysis(read_workbook(workbook_path(sid)), ANALYSIS_DATE).shortage_results
    expected = build_full_expected(ALL_SCENARIOS[sid])
    fields = ("Required_Quantity", "Inventory_Allocated", "Incoming_PO_Allocated", "Shortage_Quantity", "Priority", "Priority_Rule_ID")
    key = lambda row: tuple(str(row[name]) for name in ("Production_Order_ID", "Production_Order_Item", "Material_ID", "Plant", "Quantity_Unit"))
    actual_map = {key(row): row for row in actual.to_dict("records")}
    expected_map = {key(row): row for row in expected}
    assert actual_map.keys() == expected_map.keys()
    for row_key in actual_map:
        for field in fields:
            assert actual_map[row_key][field] == pytest.approx(expected_map[row_key][field]) if isinstance(expected_map[row_key][field], (int, float)) else actual_map[row_key][field] == expected_map[row_key][field]

def test_declared_scale_descriptions_and_reproducibility():
    minimums = {"small": (10, 5, 15), "medium": (50, 15, 50), "large": (200, 40, 150)}
    for sid, scenario in ALL_SCENARIOS.items():
        orders, products, materials = minimums[scenario.category]
        assert len(scenario.sheets["Orders"]) >= orders
        assert len({r["Product_ID"] for r in scenario.sheets["Orders"]}) >= products
        assert len({r["Component_Material_ID"] for r in scenario.sheets["BOM"]}) >= materials
        assert all(r.get("Product_Description") for r in scenario.sheets["Orders"])
        assert all(r.get("Component_Material_Description") and r.get("Material_Category") for r in scenario.sheets["BOM"])
        assert scenario == ALL_SCENARIOS[sid]

def test_catalog_and_oracles_are_complete_and_synthetic():
    catalog = json.loads((DATA / "scenario_catalog.json").read_text(encoding="utf-8"))
    assert len(catalog["scenarios"]) == 25
    assert sum(bool(item["Recommended for Demo"]) for item in catalog["scenarios"]) == 1
    for item in catalog["scenarios"]:
        oracle = json.loads((ROOT / item["Oracle Path"]).read_text(encoding="utf-8"))
        assert oracle["Expected Validation Outcome"] == "PASS"
        assert "Expected Shortage Rows" in oracle
