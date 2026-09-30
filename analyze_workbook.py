"""Run deterministic shortage analysis from the command line."""

import argparse
import sys
from datetime import date
from pathlib import Path

from src.shortage_engine import AnalysisBlockedError, run_shortage_analysis
from src.workbook_reader import WorkbookReadError, read_workbook


def main() -> int:
    """Read, validate, calculate, and print auditable results."""

    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Deterministic shortage analysis")
    parser.add_argument("workbook", type=Path, help="Path to the Excel workbook")
    parser.add_argument("--analysis-date", required=True, type=date.fromisoformat)
    args = parser.parse_args()

    try:
        result = run_shortage_analysis(read_workbook(args.workbook), args.analysis_date)
    except WorkbookReadError as exc:
        print(f"Read failed: {exc}")
        return 2
    except AnalysisBlockedError as exc:
        print("Analysis blocked by Data Errors:")
        for issue in exc.report.data_errors:
            print(f"- [{issue.code}] {issue.message}")
        return 1

    if result.shortage_results.empty:
        print("No participating production demand.")
        return 0

    columns = [
        "Production_Order_ID", "Material_ID", "Plant", "Material_Need_Date",
        "Required_Quantity", "Inventory_Allocated", "Incoming_PO_Allocated",
        "Overdue_Incoming_Quantity", "Shortage_Quantity", "Next_Receipt_Date",
        "Priority", "Priority_Rule_ID",
    ]
    print(result.shortage_results[columns].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
