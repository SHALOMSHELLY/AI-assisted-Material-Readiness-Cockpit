"""Read an Excel workbook and retain data from every worksheet."""

from io import BytesIO
from pathlib import Path
from typing import BinaryIO

import pandas as pd


class WorkbookReadError(Exception):
    """Safe workbook read error suitable for display in the UI."""


WorkbookSource = str | Path | bytes | BinaryIO


def read_workbook(source: WorkbookSource) -> dict[str, pd.DataFrame]:
    """Read every worksheet while preserving column names and cell values.

    Fully blank rows are removed.
    """

    prepared_source = BytesIO(source) if isinstance(source, bytes) else source
    try:
        sheets = pd.read_excel(
            prepared_source,
            sheet_name=None,
            engine="openpyxl",
            dtype=object,
        )
    except (FileNotFoundError, PermissionError, ValueError, OSError) as exc:
        raise WorkbookReadError(
            "Unable to read the Excel workbook. Confirm that the file exists, is not damaged "
            "or locked by another program, and uses the .xlsx format."
        ) from exc
    except Exception as exc:  # The reader boundary converts library errors to a safe message.
        raise WorkbookReadError(
            "Unable to read the Excel workbook because an unexpected reader error occurred. "
            "Retry with a valid .xlsx file."
        ) from exc

    # :,Excel.
    #  Preserve original indexes so validation errors map to real Excel row numbers.
    return {name: frame.dropna(how="all") for name, frame in sheets.items()}
