"""Export deterministic analysis results."""

from io import BytesIO

import pandas as pd
from openpyxl.styles import Font, PatternFill

from src.shortage_engine import AnalysisResult


def results_to_excel(result: AnalysisResult) -> bytes:
    """Export shortage results, requirements, and validation to one workbook."""

    summary = pd.DataFrame([result.validation_report.summary()])
    issue_columns = [
        "severity", "code", "sheet", "row", "field", "error_value", "message", "fix",
    ]
    issues = pd.DataFrame(
        [issue.to_dict() for issue in result.validation_report.issues],
        columns=issue_columns,
    )
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        result.shortage_results.to_excel(writer, sheet_name="Shortage_Results", index=False)
        result.material_requirements.to_excel(writer, sheet_name="Material_Requirements", index=False)
        summary.to_excel(writer, sheet_name="Validation_Summary", index=False)
        issues.to_excel(writer, sheet_name="Validation_Issues", index=False)
        for worksheet in writer.book.worksheets:
            worksheet.freeze_panes = "A2"
            worksheet.auto_filter.ref = worksheet.dimensions
            for cell in worksheet[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill(fill_type="solid", fgColor="1F4E78")
            for column_cells in worksheet.columns:
                width = min(35, max(12, max(len(str(cell.value or "")) for cell in column_cells) + 2))
                worksheet.column_dimensions[column_cells[0].column_letter].width = width
    return output.getvalue()


def results_to_csv(result: AnalysisResult) -> bytes:
    """Export the main shortage results as UTF-8 CSV."""

    return result.shortage_results.to_csv(index=False).encode("utf-8-sig")
