"""Phase 2 validation tests."""

from copy import deepcopy
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from src.validators import validate_workbook
from src.workbook_reader import WorkbookReadError, read_workbook


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "test_data" / "sample_workbook.xlsx"
INVALID_EXAMPLE = ROOT / "test_data" / "invalid_validation_example.xlsx"
ANALYSIS_DATE = date(2026, 9, 25)


@pytest.fixture()
def valid_sheets() -> dict[str, pd.DataFrame]:
    """Read an independent valid example for each test."""

    return read_workbook(SAMPLE)


def codes(report) -> set[str]:
    return {issue.code for issue in report.issues}


def test_sample_workbook_is_valid(valid_sheets):
    report = validate_workbook(valid_sheets, ANALYSIS_DATE)
    assert report.is_valid
    assert report.summary() == {"is_valid": True, "data_error_count": 0, "warning_count": 0, "ignored_count": 0, "total_issue_count": 0}


def test_material_metadata_must_be_consistent_within_plant(valid_sheets):
    bom = valid_sheets["BOM"].copy()
    bom["Component_Material_Description"] = bom["Component_Material_ID"].astype(str)
    bom["Material_Category"] = "Component"
    duplicate = bom.iloc[[0]].copy()
    duplicate["BOM_ID"] = "BOM-METADATA-CHECK"
    duplicate["BOM_Item_ID"] = "999"
    duplicate["Component_Material_Description"] = "Conflicting description"
    valid_sheets["BOM"] = pd.concat([bom, duplicate], ignore_index=True)
    report = validate_workbook(valid_sheets, ANALYSIS_DATE)
    assert "INCONSISTENT_MATERIAL_METADATA" in codes(report)


def test_missing_sheet_is_data_error(valid_sheets):
    valid_sheets.pop("BOM")
    assert "MISSING_SHEET" in codes(validate_workbook(valid_sheets, ANALYSIS_DATE))


def test_extra_sheet_is_warning(valid_sheets):
    valid_sheets["Notes"] = pd.DataFrame({"Text": ["not analyzed"]})
    report = validate_workbook(valid_sheets, ANALYSIS_DATE)
    assert report.is_valid and "EXTRA_SHEET" in codes(report)


def test_missing_column_is_data_error(valid_sheets):
    valid_sheets["Orders"] = valid_sheets["Orders"].drop(columns=["Plant"])
    assert "MISSING_COLUMN" in codes(validate_workbook(valid_sheets, ANALYSIS_DATE))


def test_inventory_duplicate_key_is_data_error(valid_sheets):
    valid_sheets["Inventory"] = pd.concat([valid_sheets["Inventory"], valid_sheets["Inventory"].iloc[[0]]], ignore_index=True)
    assert "DUPLICATE_KEY" in codes(validate_workbook(valid_sheets, ANALYSIS_DATE))


def test_inventory_snapshot_dates_must_match(valid_sheets):
    valid_sheets["Inventory"].loc[1, "Snapshot_Date"] = pd.Timestamp("2026-09-24")
    assert "MULTIPLE_SNAPSHOT_DATES" in codes(validate_workbook(valid_sheets, ANALYSIS_DATE))


def test_inventory_snapshot_cannot_be_future(valid_sheets):
    valid_sheets["Inventory"]["Snapshot_Date"] = pd.Timestamp("2026-09-26")
    assert "FUTURE_SNAPSHOT_DATE" in codes(validate_workbook(valid_sheets, ANALYSIS_DATE))


def test_missing_inventory_is_warning_and_not_error(valid_sheets):
    valid_sheets["Inventory"] = valid_sheets["Inventory"].iloc[0:0]
    report = validate_workbook(valid_sheets, ANALYSIS_DATE)
    assert "MISSING_INVENTORY_AS_ZERO" in codes(report)
    assert report.is_valid


def test_unrelated_incoming_po_is_ignored(valid_sheets):
    valid_sheets["Incoming_PO"].loc[0, "Material_ID"] = "UNRELATED"
    report = validate_workbook(valid_sheets, ANALYSIS_DATE)
    assert "UNRELATED_INCOMING_PO" in codes(report)
    assert report.is_valid


def test_source_order_fields_must_be_paired(valid_sheets):
    valid_sheets["Production_Orders"].loc[0, "Source_Sales_Order_Item"] = None
    assert "SOURCE_ORDER_PAIR" in codes(validate_workbook(valid_sheets, ANALYSIS_DATE))


def test_make_to_stock_is_allowed(valid_sheets):
    valid_sheets["Production_Orders"].loc[0, ["Source_Sales_Order_ID", "Source_Sales_Order_Item"]] = None
    assert "SOURCE_ORDER_PAIR" not in codes(validate_workbook(valid_sheets, ANALYSIS_DATE))


def test_bom_effectivity_includes_boundary(valid_sheets):
    valid_sheets["BOM"].loc[0, "Valid_From"] = pd.Timestamp("2026-09-30")
    valid_sheets["BOM"].loc[0, "Valid_To"] = pd.Timestamp("2026-09-30")
    assert "EFFECTIVE_BOM_NOT_FOUND" not in codes(validate_workbook(valid_sheets, ANALYSIS_DATE))


def test_bom_outside_need_date_is_data_error(valid_sheets):
    valid_sheets["BOM"].loc[0, "Valid_To"] = pd.Timestamp("2026-09-29")
    assert "EFFECTIVE_BOM_NOT_FOUND" in codes(validate_workbook(valid_sheets, ANALYSIS_DATE))


def test_open_quantity_must_reconcile(valid_sheets):
    valid_sheets["Incoming_PO"].loc[0, "Open_Quantity"] = 11
    assert "OPEN_QUANTITY_MISMATCH" in codes(validate_workbook(valid_sheets, ANALYSIS_DATE))


def test_remaining_quantity_must_reconcile(valid_sheets):
    valid_sheets["Production_Orders"].loc[0, "Remaining_Quantity"] = 9
    assert "REMAINING_QUANTITY_MISMATCH" in codes(validate_workbook(valid_sheets, ANALYSIS_DATE))


def test_unit_mismatch_is_data_error(valid_sheets):
    valid_sheets["Inventory"].loc[0, "Base_Unit"] = "KG"
    assert "INVENTORY_UNIT_MISMATCH" in codes(validate_workbook(valid_sheets, ANALYSIS_DATE))


def test_safety_stock_must_be_consistent(valid_sheets):
    valid_sheets["Inventory"].loc[1, "Safety_Stock"] = 3
    assert "INCONSISTENT_SAFETY_STOCK" in codes(validate_workbook(valid_sheets, ANALYSIS_DATE))


def test_multilevel_bom_is_unsupported(valid_sheets):
    extra = deepcopy(valid_sheets["BOM"].iloc[0])
    extra["BOM_ID"] = "BOM002"
    extra["Parent_Product_ID"] = "RM001"
    extra["Component_Material_ID"] = "RM002"
    valid_sheets["BOM"] = pd.concat([valid_sheets["BOM"], pd.DataFrame([extra])], ignore_index=True)
    assert "UNSUPPORTED_MULTILEVEL_BOM" in codes(validate_workbook(valid_sheets, ANALYSIS_DATE))


def test_reader_returns_english_error_for_bad_file(tmp_path):
    bad_file = tmp_path / "bad.xlsx"
    bad_file.write_text("not an excel workbook", encoding="utf-8")
    with pytest.raises(WorkbookReadError, match="Unable to read"):
        read_workbook(bad_file)


def test_invalid_example_has_expected_summary():
    report = validate_workbook(read_workbook(INVALID_EXAMPLE), ANALYSIS_DATE)
    assert report.summary() == {
        "is_valid": False,
        "data_error_count": 5,
        "warning_count": 2,
        "ignored_count": 1,
        "total_issue_count": 8,
    }


def test_missing_required_value_is_data_error(valid_sheets):
    valid_sheets["Orders"].loc[0, "Product_ID"] = None
    assert "MISSING_REQUIRED_VALUE" in codes(validate_workbook(valid_sheets, ANALYSIS_DATE))


def test_invalid_number_is_data_error(valid_sheets):
    valid_sheets["Orders"].loc[0, "Requested_Quantity"] = "ten"
    assert "INVALID_NUMBER" in codes(validate_workbook(valid_sheets, ANALYSIS_DATE))


def test_negative_quantity_is_data_error(valid_sheets):
    valid_sheets["Inventory"].loc[0, "Quantity"] = -1
    assert "INVALID_QUANTITY_RANGE" in codes(validate_workbook(valid_sheets, ANALYSIS_DATE))


def test_invalid_date_is_data_error(valid_sheets):
    valid_sheets["Orders"].loc[0, "Requested_Delivery_Date"] = "not-a-date"
    assert "INVALID_DATE" in codes(validate_workbook(valid_sheets, ANALYSIS_DATE))


def test_invalid_status_is_data_error(valid_sheets):
    valid_sheets["Orders"].loc[0, "Order_Status"] = "UNKNOWN"
    assert "INVALID_STATUS" in codes(validate_workbook(valid_sheets, ANALYSIS_DATE))


def test_po_status_and_flag_conflict_is_data_error(valid_sheets):
    valid_sheets["Incoming_PO"].loc[0, "PO_Status"] = "OPEN"
    valid_sheets["Incoming_PO"].loc[0, "Completely_Delivered_Flag"] = True
    assert "PO_STATUS_FLAG_CONFLICT" in codes(validate_workbook(valid_sheets, ANALYSIS_DATE))


def test_source_order_must_exist(valid_sheets):
    valid_sheets["Production_Orders"].loc[0, "Source_Sales_Order_ID"] = "NOT_FOUND"
    assert "SOURCE_ORDER_NOT_FOUND" in codes(validate_workbook(valid_sheets, ANALYSIS_DATE))


def test_production_date_range_is_ordered(valid_sheets):
    valid_sheets["Production_Orders"].loc[0, "Planned_End_Date"] = pd.Timestamp("2026-09-29")
    assert "PRODUCTION_DATE_RANGE" in codes(validate_workbook(valid_sheets, ANALYSIS_DATE))


def test_bom_date_range_is_ordered(valid_sheets):
    valid_sheets["BOM"].loc[0, "Valid_To"] = pd.Timestamp("2025-12-31")
    assert "BOM_DATE_RANGE" in codes(validate_workbook(valid_sheets, ANALYSIS_DATE))


def test_po_unit_mismatch_is_data_error(valid_sheets):
    valid_sheets["Incoming_PO"].loc[0, "Quantity_Unit"] = "KG"
    assert "PO_UNIT_MISMATCH" in codes(validate_workbook(valid_sheets, ANALYSIS_DATE))


def test_effective_bom_is_required(valid_sheets):
    valid_sheets["BOM"].loc[0, "Parent_Product_ID"] = "OTHER_PRODUCT"
    assert "EFFECTIVE_BOM_NOT_FOUND" in codes(validate_workbook(valid_sheets, ANALYSIS_DATE))


def test_excel_row_number_survives_blank_rows(valid_sheets):
    orders = valid_sheets["Orders"].copy()
    orders.index = [3]  # Pandas index 3 corresponds to Excel row 5 after blank rows.
    orders.loc[3, "Requested_Quantity"] = -1
    valid_sheets["Orders"] = orders
    report = validate_workbook(valid_sheets, ANALYSIS_DATE)
    issue = next(item for item in report.issues if item.code == "INVALID_QUANTITY_RANGE")
    assert issue.row == 5


def test_cancelled_po_with_different_unit_is_ignored_before_unit_check(valid_sheets):
    valid_sheets["Incoming_PO"].loc[0, "PO_Status"] = "CANCELLED"
    valid_sheets["Incoming_PO"].loc[0, "Quantity_Unit"] = "KG"
    report = validate_workbook(valid_sheets, ANALYSIS_DATE)
    assert "INACTIVE_INCOMING_PO" in codes(report)
    assert "PO_UNIT_MISMATCH" not in codes(report)


def test_deleted_po_with_different_unit_is_ignored_before_unit_check(valid_sheets):
    valid_sheets["Incoming_PO"].loc[0, "Deletion_Flag"] = True
    valid_sheets["Incoming_PO"].loc[0, "Quantity_Unit"] = "KG"
    report = validate_workbook(valid_sheets, ANALYSIS_DATE)
    assert "INACTIVE_INCOMING_PO" in codes(report)
    assert "PO_UNIT_MISMATCH" not in codes(report)


def test_zero_open_quantity_po_is_outside_future_supply_scope(valid_sheets):
    valid_sheets["Incoming_PO"].loc[0, "Received_Quantity"] = 15
    valid_sheets["Incoming_PO"].loc[0, "Open_Quantity"] = 0
    valid_sheets["Incoming_PO"].loc[0, "Quantity_Unit"] = "KG"
    report = validate_workbook(valid_sheets, ANALYSIS_DATE)
    assert "INACTIVE_INCOMING_PO" in codes(report)
    assert "PO_UNIT_MISMATCH" not in codes(report)


def test_zero_remaining_quantity_does_not_require_bom(valid_sheets):
    valid_sheets["Production_Orders"].loc[0, "Confirmed_Yield_Quantity"] = 10
    valid_sheets["Production_Orders"].loc[0, "Remaining_Quantity"] = 0
    valid_sheets["BOM"] = valid_sheets["BOM"].iloc[0:0]
    report = validate_workbook(valid_sheets, ANALYSIS_DATE)
    assert "EFFECTIVE_BOM_NOT_FOUND" not in codes(report)


def test_other_plant_bom_does_not_trigger_multilevel_error(valid_sheets):
    extra = deepcopy(valid_sheets["BOM"].iloc[0])
    extra["BOM_ID"] = "BOM_OTHER_PLANT"
    extra["BOM_Item_ID"] = "10"
    extra["Parent_Product_ID"] = "RM001"
    extra["Plant"] = "2020"
    extra["Component_Material_ID"] = "RM002"
    valid_sheets["BOM"] = pd.concat([valid_sheets["BOM"], pd.DataFrame([extra])], ignore_index=True)
    assert "UNSUPPORTED_MULTILEVEL_BOM" not in codes(validate_workbook(valid_sheets, ANALYSIS_DATE))


def test_expired_unrelated_bom_does_not_trigger_multilevel_error(valid_sheets):
    extra = deepcopy(valid_sheets["BOM"].iloc[0])
    extra["BOM_ID"] = "BOM_EXPIRED"
    extra["BOM_Item_ID"] = "10"
    extra["Parent_Product_ID"] = "RM001"
    extra["Component_Material_ID"] = "RM002"
    extra["Valid_To"] = pd.Timestamp("2026-09-29")
    valid_sheets["BOM"] = pd.concat([valid_sheets["BOM"], pd.DataFrame([extra])], ignore_index=True)
    assert "UNSUPPORTED_MULTILEVEL_BOM" not in codes(validate_workbook(valid_sheets, ANALYSIS_DATE))


def test_multiple_effective_boms_are_data_error(valid_sheets):
    extra = deepcopy(valid_sheets["BOM"].iloc[0])
    extra["BOM_ID"] = "BOM002"
    extra["BOM_Item_ID"] = "10"
    extra["Alternative_BOM"] = "02"
    valid_sheets["BOM"] = pd.concat([valid_sheets["BOM"], pd.DataFrame([extra])], ignore_index=True)
    assert "MULTIPLE_EFFECTIVE_BOMS" in codes(validate_workbook(valid_sheets, ANALYSIS_DATE))


def test_boolean_format_matches_documented_rule(valid_sheets):
    valid_sheets["Incoming_PO"].loc[0, "Deletion_Flag"] = 0
    valid_sheets["Incoming_PO"].loc[0, "Completely_Delivered_Flag"] = 1
    numeric_report = validate_workbook(valid_sheets, ANALYSIS_DATE)
    assert "INVALID_BOOLEAN" not in codes(numeric_report)
    assert "INACTIVE_INCOMING_PO" in codes(numeric_report)

    valid_sheets["Incoming_PO"].loc[0, "Completely_Delivered_Flag"] = "FALSE"
    text_report = validate_workbook(valid_sheets, ANALYSIS_DATE)
    assert "INVALID_BOOLEAN" in codes(text_report)


def add_second_bom_item(valid_sheets, field, value):
    """Add another item in the same BOM with one conflicting header value."""

    extra = deepcopy(valid_sheets["BOM"].iloc[0])
    extra["BOM_Item_ID"] = "20"
    extra["Component_Material_ID"] = "RM002"
    extra[field] = value
    valid_sheets["BOM"] = pd.concat(
        [valid_sheets["BOM"], pd.DataFrame([extra])], ignore_index=True
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("Base_Quantity", 2),
        ("Base_Quantity_Unit", "KG"),
        ("Parent_Product_ID", "FG999"),
        ("Plant", "2020"),
    ],
)
def test_bom_header_inconsistency_is_data_error(valid_sheets, field, value):
    add_second_bom_item(valid_sheets, field, value)
    report = validate_workbook(valid_sheets, ANALYSIS_DATE)
    issue = next(item for item in report.data_errors if item.code == "INCONSISTENT_BOM_HEADER")
    assert issue.field == field
    assert "2, 3" in issue.message
