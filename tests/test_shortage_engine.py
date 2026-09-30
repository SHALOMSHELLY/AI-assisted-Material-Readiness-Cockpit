"""Phase 3 deterministic shortage-engine tests."""

from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest

from src.priority_rules import determine_priority
from src.shortage_engine import AnalysisBlockedError, run_shortage_analysis
from src.workbook_reader import read_workbook


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "test_data" / "sample_workbook.xlsx"
INVALID = ROOT / "test_data" / "invalid_validation_example.xlsx"
ANALYSIS_DATE = date(2026, 9, 25)


@pytest.fixture()
def sheets() -> dict[str, pd.DataFrame]:
    return read_workbook(SAMPLE)


def add_production_order(
    sheets: dict[str, pd.DataFrame],
    order_id: str,
    start: str,
    remaining: float,
    plant: str = "1010",
) -> None:
    row = deepcopy(sheets["Production_Orders"].iloc[0]).astype(object)
    row["Production_Order_ID"] = order_id
    row["Source_Sales_Order_ID"] = None
    row["Source_Sales_Order_Item"] = None
    row["Plant"] = plant
    row["Total_Quantity"] = remaining
    row["Confirmed_Yield_Quantity"] = 0
    row["Remaining_Quantity"] = remaining
    start_date = date.fromisoformat(start)
    row["Planned_Start_Date"] = start_date
    row["Planned_End_Date"] = start_date + timedelta(days=1)
    sheets["Production_Orders"] = pd.concat(
        [sheets["Production_Orders"], pd.DataFrame([row])], ignore_index=True
    )


def test_sample_workbook_calculation(sheets):
    result = run_shortage_analysis(sheets, ANALYSIS_DATE)
    row = result.shortage_results.iloc[0]
    assert row["Required_Quantity"] == pytest.approx(16)
    assert row["Unrestricted_Inventory"] == pytest.approx(12)
    assert row["Safety_Stock"] == pytest.approx(2)
    assert row["Usable_Inventory"] == pytest.approx(10)
    assert row["Inventory_Allocated"] == pytest.approx(10)
    assert row["Incoming_PO_Allocated"] == pytest.approx(6)
    assert row["Shortage_Quantity"] == pytest.approx(0)
    assert row["Next_Receipt_Date"] == date(2026, 9, 28)
    assert row["Priority"] == "Low"
    assert row["Priority_Rule_ID"] == "P4"


def test_bom_base_quantity_not_one(sheets):
    sheets["BOM"].loc[0, "Base_Quantity"] = 2
    sheets["BOM"].loc[0, "Component_Quantity"] = 3
    row = run_shortage_analysis(sheets, ANALYSIS_DATE).shortage_results.iloc[0]
    assert row["Required_Quantity"] == pytest.approx(12)


def test_safety_stock_is_deducted_once_across_storage_locations(sheets):
    extra = deepcopy(sheets["Inventory"].iloc[0])
    extra["Storage_Location"] = "0003"
    extra["Quantity"] = 8
    sheets["Inventory"] = pd.concat([sheets["Inventory"], pd.DataFrame([extra])], ignore_index=True)
    row = run_shortage_analysis(sheets, ANALYSIS_DATE).shortage_results.iloc[0]
    assert row["Unrestricted_Inventory"] == pytest.approx(20)
    assert row["Safety_Stock"] == pytest.approx(2)
    assert row["Usable_Inventory"] == pytest.approx(18)


def test_non_unrestricted_stock_is_not_available(sheets):
    row = run_shortage_analysis(sheets, ANALYSIS_DATE).shortage_results.iloc[0]
    assert row["Unrestricted_Inventory"] == pytest.approx(12)
    assert row["Usable_Inventory"] == pytest.approx(10)


def test_late_po_is_not_allocated(sheets):
    sheets["Incoming_PO"].loc[0, "Expected_Receipt_Date"] = pd.Timestamp("2026-10-01")
    row = run_shortage_analysis(sheets, ANALYSIS_DATE).shortage_results.iloc[0]
    assert row["Incoming_PO_Allocated"] == pytest.approx(0)
    assert row["Late_Incoming_Quantity"] == pytest.approx(10)
    assert row["Shortage_Quantity"] == pytest.approx(6)


def test_deleted_po_is_not_allocated(sheets):
    sheets["Incoming_PO"].loc[0, "Deletion_Flag"] = True
    row = run_shortage_analysis(sheets, ANALYSIS_DATE).shortage_results.iloc[0]
    assert row["Incoming_PO_Allocated"] == pytest.approx(0)
    assert row["Shortage_Quantity"] == pytest.approx(6)


def test_closed_production_order_creates_no_demand(sheets):
    sheets["Production_Orders"].loc[0, "Order_Status"] = "COMPLETED"
    result = run_shortage_analysis(sheets, ANALYSIS_DATE)
    assert result.material_requirements.empty
    assert result.shortage_results.empty


def test_earlier_order_receives_inventory_first(sheets):
    add_production_order(sheets, "PR2000", "2026-09-29", 5)
    results = run_shortage_analysis(sheets, ANALYSIS_DATE).shortage_results
    earlier = results.loc[results["Production_Order_ID"] == "PR2000"].iloc[0]
    later = results.loc[results["Production_Order_ID"] == "PR3001"].iloc[0]
    assert earlier["Allocation_Sequence"] == 1
    assert earlier["Inventory_Allocated"] == pytest.approx(10)
    assert later["Inventory_Allocated"] == pytest.approx(0)
    assert later["Incoming_PO_Allocated"] == pytest.approx(10)
    assert later["Shortage_Quantity"] == pytest.approx(6)


def test_same_day_orders_are_sorted_by_id(sheets):
    add_production_order(sheets, "PR2000", "2026-09-30", 5)
    results = run_shortage_analysis(sheets, ANALYSIS_DATE).shortage_results
    assert list(results["Production_Order_ID"]) == ["PR2000", "PR3001"]


def test_po_quantity_is_not_reused(sheets):
    sheets["Inventory"]["Quantity"] = 0
    sheets["Inventory"]["Safety_Stock"] = 0
    add_production_order(sheets, "PR4000", "2026-10-01", 2)
    results = run_shortage_analysis(sheets, ANALYSIS_DATE).shortage_results
    assert results["Incoming_PO_Allocated"].sum() == pytest.approx(10)
    assert results["Shortage_Quantity"].sum() == pytest.approx(10)


def test_inventory_does_not_cross_plants(sheets):
    bom_2020 = sheets["BOM"].copy()
    bom_2020["BOM_ID"] = "BOM2020"
    bom_2020["Plant"] = "2020"
    sheets["BOM"] = pd.concat([sheets["BOM"], bom_2020], ignore_index=True)
    add_production_order(sheets, "PR2020", "2026-09-29", 1, plant="2020")
    results = run_shortage_analysis(sheets, ANALYSIS_DATE).shortage_results
    row_2020 = results.loc[results["Production_Order_ID"] == "PR2020"].iloc[0]
    assert row_2020["Usable_Inventory"] == pytest.approx(0)
    assert row_2020["Shortage_Quantity"] == pytest.approx(2)


def test_invalid_workbook_blocks_analysis():
    with pytest.raises(AnalysisBlockedError) as caught:
        run_shortage_analysis(read_workbook(INVALID), ANALYSIS_DATE)
    assert len(caught.value.report.data_errors) == 5


def test_inconsistent_bom_header_is_blocked_before_bom_builder(sheets):
    extra = deepcopy(sheets["BOM"].iloc[0])
    extra["BOM_Item_ID"] = "20"
    extra["Component_Material_ID"] = "RM002"
    extra["Base_Quantity"] = 2
    sheets["BOM"] = pd.concat([sheets["BOM"], pd.DataFrame([extra])], ignore_index=True)
    with pytest.raises(AnalysisBlockedError) as caught:
        run_shortage_analysis(sheets, ANALYSIS_DATE)
    assert any(issue.code == "INCONSISTENT_BOM_HEADER" for issue in caught.value.report.data_errors)


def test_overdue_open_po_is_reported_but_not_allocated(sheets):
    sheets["Incoming_PO"].loc[0, "Expected_Receipt_Date"] = pd.Timestamp("2026-09-24")
    result = run_shortage_analysis(sheets, ANALYSIS_DATE)
    row = result.shortage_results.iloc[0]
    assert any(issue.code == "OVERDUE_INCOMING_PO" for issue in result.validation_report.warnings)
    assert row["Incoming_PO_Allocated"] == pytest.approx(0)
    assert row["Overdue_Incoming_Quantity"] == pytest.approx(10)
    assert row["Overdue_PO_Lines"] == "PO2001/10/1:10"
    assert row["Shortage_Quantity"] == pytest.approx(6)
    assert pd.isna(row["Next_Receipt_Date"])


def test_receipt_on_analysis_date_is_not_overdue_and_can_be_allocated(sheets):
    sheets["Incoming_PO"].loc[0, "Expected_Receipt_Date"] = pd.Timestamp(ANALYSIS_DATE)
    result = run_shortage_analysis(sheets, ANALYSIS_DATE)
    row = result.shortage_results.iloc[0]
    assert not any(issue.code == "OVERDUE_INCOMING_PO" for issue in result.validation_report.warnings)
    assert row["Overdue_Incoming_Quantity"] == pytest.approx(0)
    assert row["Incoming_PO_Allocated"] == pytest.approx(6)
    assert row["Next_Receipt_Date"] == ANALYSIS_DATE


def test_cli_reports_invalid_workbook_without_traceback():
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "analyze_workbook.py"),
            str(INVALID),
            "--analysis-date",
            "2026-09-25",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 1
    assert "Data Error" in completed.stdout
    assert "Traceback" not in completed.stdout + completed.stderr


def test_same_input_is_deterministic(sheets):
    first = run_shortage_analysis(sheets, ANALYSIS_DATE).shortage_results
    second = run_shortage_analysis(read_workbook(SAMPLE), ANALYSIS_DATE).shortage_results
    pd.testing.assert_frame_equal(first, second)


@pytest.mark.parametrize(
    ("shortage", "days_until_start", "receipt_offset", "priority", "rule_id"),
    [
        (1, -1, None, "Critical", "P1"),
        (1, 2, None, "Critical", "P1"),
        (1, 3, None, "High", "P2"),
        (1, 7, None, "High", "P2"),
        (1, 8, None, "Medium", "P3A"),
        (0, 5, 0, "Medium", "P3B"),
        (0, 5, 1, "Medium", "P3B"),
        (0, 5, 2, "Low", "P4"),
    ],
)
def test_priority_boundaries(shortage, days_until_start, receipt_offset, priority, rule_id):
    start = ANALYSIS_DATE + timedelta(days=days_until_start)
    receipt = None if receipt_offset is None else start - timedelta(days=receipt_offset)
    decision = determine_priority(shortage, start, ANALYSIS_DATE, receipt)
    assert (decision.priority, decision.rule_id) == (priority, rule_id)


def test_data_error_priority_rule():
    decision = determine_priority(0, ANALYSIS_DATE, ANALYSIS_DATE, data_error=True)
    assert (decision.priority, decision.rule_id) == ("Data Error", "P0")
