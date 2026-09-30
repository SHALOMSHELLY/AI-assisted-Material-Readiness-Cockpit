"""Filter participating PO schedule lines and prepare stable allocation order."""

from datetime import date
from typing import Any

import pandas as pd


def _text(value: Any) -> str:
    return "" if pd.isna(value) else str(value).strip()


def _flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return bool(int(value))


def build_incoming_receipts(
    incoming_po: pd.DataFrame, analysis_date: date
) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    """Keep eligible OPEN or PARTIALLY_RECEIVED rows with positive open quantity."""

    receipts: list[dict[str, Any]] = []
    for _, row in incoming_po.iterrows():
        status = _text(row["PO_Status"]).upper()
        open_quantity = float(row["Open_Quantity"])
        if (
            status not in {"OPEN", "PARTIALLY_RECEIVED"}
            or _flag(row["Deletion_Flag"])
            or _flag(row["Completely_Delivered_Flag"])
            or open_quantity <= 0
        ):
            continue
        receipt_date = pd.to_datetime(row["Expected_Receipt_Date"]).date()
        receipts.append(
            {
                "PO_ID": _text(row["PO_ID"]),
                "PO_Item": _text(row["PO_Item"]),
                "Schedule_Line": _text(row["Schedule_Line"]),
                "Material_ID": _text(row["Material_ID"]),
                "Plant": _text(row["Plant"]),
                "Quantity_Unit": _text(row["Quantity_Unit"]),
                "Expected_Receipt_Date": receipt_date,
                "Is_Overdue": receipt_date < analysis_date,
                "Open_Quantity": open_quantity,
                "Remaining_Open_Quantity": open_quantity,
            }
        )
    receipts.sort(
        key=lambda row: (
            row["Expected_Receipt_Date"],
            row["PO_ID"],
            row["PO_Item"],
            row["Schedule_Line"],
        ),
    )
    pools: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for receipt in receipts:
        key = (receipt["Material_ID"], receipt["Plant"], receipt["Quantity_Unit"])
        pools.setdefault(key, []).append(receipt)
    return pools


def matching_receipts(
    receipts: dict[tuple[str, str, str], list[dict[str, Any]]], key: tuple[str, str, str]
) -> list[dict[str, Any]]:
    """Return receipts matching material, plant, and unit."""

    return receipts.get(key, [])
