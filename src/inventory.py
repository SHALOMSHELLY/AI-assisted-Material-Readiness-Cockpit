"""Aggregate inventory and deduct safety stock once per material and plant."""

from typing import Any

import pandas as pd


def _text(value: Any) -> str:
    return "" if pd.isna(value) else str(value).strip()


def build_inventory_pools(inventory: pd.DataFrame) -> dict[tuple[str, str, str], dict[str, float]]:
    """Aggregate UNRESTRICTED stock and calculate usable inventory.

    Other stock types remain in the input but are excluded from supply.
    """

    pools: dict[tuple[str, str, str], dict[str, float]] = {}
    grouped = inventory.groupby(["Material_ID", "Plant", "Base_Unit"], sort=True, dropna=False)
    for (material, plant, unit), rows in grouped:
        unrestricted = float(
            pd.to_numeric(
                rows.loc[rows["Stock_Type"].map(lambda value: _text(value).upper()) == "UNRESTRICTED", "Quantity"]
            ).sum()
        )
        safety_values = pd.to_numeric(rows["Safety_Stock"], errors="raise").unique()
        safety_stock = float(safety_values[0]) if len(safety_values) else 0.0
        usable = max(0.0, unrestricted - safety_stock)
        pools[(_text(material), _text(plant), _text(unit))] = {
            "Unrestricted_Inventory": unrestricted,
            "Safety_Stock": safety_stock,
            "Usable_Inventory": usable,
            "Remaining_Inventory": usable,
        }
    return pools
