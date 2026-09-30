"""Select the effective single-level BOM and calculate component requirements."""

from datetime import date
from typing import Any

import pandas as pd

from config.settings import ACTIVE_PRODUCTION_ORDER_STATUSES


def _text(value: Any) -> str:
    return "" if pd.isna(value) else str(value).strip()


def _date(value: Any) -> date:
    return pd.to_datetime(value).date()


def build_material_requirements(production_orders: pd.DataFrame, bom: pd.DataFrame) -> pd.DataFrame:
    """Explode one BOM level for active orders with positive remaining quantity.

    Repeated component lines within the same production order are aggregated.
    """

    records: list[dict[str, Any]] = []
    prepared_bom = bom.copy()
    prepared_bom["_parent"] = prepared_bom["Parent_Product_ID"].map(_text)
    prepared_bom["_plant"] = prepared_bom["Plant"].map(_text)
    prepared_bom["_base_unit"] = prepared_bom["Base_Quantity_Unit"].map(_text)
    prepared_bom["_valid_from"] = pd.to_datetime(prepared_bom["Valid_From"], errors="coerce")
    prepared_bom["_valid_to"] = pd.to_datetime(prepared_bom["Valid_To"], errors="coerce")
    bom_by_product_plant = {
        (_text(product), _text(plant)): group
        for (product, plant), group in prepared_bom.groupby(["_parent", "_plant"], sort=False)
    }
    active = production_orders[
        production_orders["Order_Status"].map(lambda value: _text(value).upper()).isin(ACTIVE_PRODUCTION_ORDER_STATUSES)
        & (pd.to_numeric(production_orders["Remaining_Quantity"], errors="coerce") > 0)
    ].copy()
    active["_need_date"] = active["Planned_Start_Date"].map(_date)
    active = active.sort_values(
        ["_need_date", "Production_Order_ID", "Production_Order_Item"],
        kind="stable",
    )

    for _, order in active.iterrows():
        need_date = order["_need_date"]
        need_timestamp = pd.Timestamp(need_date)
        product = _text(order["Product_ID"])
        plant = _text(order["Plant"])
        order_unit = _text(order["Quantity_Unit"])
        product_rows = bom_by_product_plant.get((product, plant), prepared_bom.iloc[0:0])
        candidates = product_rows[
            (product_rows["_base_unit"] == order_unit)
            & (product_rows["_valid_from"] <= need_timestamp)
            & (product_rows["_valid_to"].isna() | (product_rows["_valid_to"] >= need_timestamp))
        ]
        choices = candidates[["BOM_ID", "BOM_Usage", "Alternative_BOM"]].astype(str).drop_duplicates()
        if len(choices) != 1:
            raise ValueError("Validated input must contain exactly one effective BOM for each participating order.")
        choice = tuple(choices.iloc[0])
        selected = candidates[
            (candidates["BOM_ID"].astype(str) == choice[0])
            & (candidates["BOM_Usage"].astype(str) == choice[1])
            & (candidates["Alternative_BOM"].astype(str) == choice[2])
        ].copy()
        base_quantities = pd.to_numeric(selected["Base_Quantity"], errors="raise").unique()
        if len(base_quantities) != 1:
            raise ValueError("Validated BOM rows must use one Base_Quantity.")
        base_quantity = float(base_quantities[0])
        remaining = float(order["Remaining_Quantity"])

        grouped = selected.groupby(["Component_Material_ID", "Component_Unit"], sort=True, dropna=False)
        for (material, component_unit), component_rows in grouped:
            component_quantity = float(pd.to_numeric(component_rows["Component_Quantity"]).sum())
            required_quantity = remaining / base_quantity * component_quantity
            records.append(
                {
                    "Production_Order_ID": _text(order["Production_Order_ID"]),
                    "Production_Order_Item": _text(order["Production_Order_Item"]),
                    "Source_Sales_Order_ID": _text(order["Source_Sales_Order_ID"]),
                    "Source_Sales_Order_Item": _text(order["Source_Sales_Order_Item"]),
                    "Product_ID": product,
                    "Material_ID": _text(material),
                    "Plant": plant,
                    "Material_Need_Date": need_date,
                    "Required_Quantity": required_quantity,
                    "Quantity_Unit": _text(component_unit),
                    "Remaining_Production_Quantity": remaining,
                    "BOM_ID": choice[0],
                    "BOM_Base_Quantity": base_quantity,
                    "BOM_Component_Quantity": component_quantity,
                    "Explosion_Level": 1,
                    "Requirement_Explanation": (
                        f" Remaining production quantity {remaining:g} ÷ BOM base quantity "
                        f"{base_quantity:g} × component quantity {component_quantity:g} = "
                        f"{required_quantity:g} {_text(component_unit)}."
                    ),
                }
            )
    return pd.DataFrame(records)
