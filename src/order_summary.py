"""Order- and material-level cockpit aggregations."""

from __future__ import annotations

import pandas as pd


RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}


def _join(values) -> str:
    return ", ".join(sorted({str(value) for value in values if pd.notna(value) and str(value).strip()}))


def _highest(values) -> str:
    candidates = [str(value) for value in values if pd.notna(value)]
    return min(candidates, key=lambda value: RANK.get(value, 99), default="Low")


DEMAND_IDENTITY = [
    "Sales_Order_ID", "Sales_Order_Item", "Production_Order_ID",
    "Production_Order_Item", "Material_ID", "Plant", "Quantity_Unit",
]


def _unique_material_demands(exceptions: pd.DataFrame) -> pd.DataFrame:
    """Return one quantity row per calculated material demand.

    A single demand can legitimately generate shortage, late-supply and
    overdue-supply exceptions. Quantities describe the demand, not each
    exception, so they must be counted once.
    """
    material = exceptions[
        exceptions["Sales_Order_ID"].notna()
        & exceptions["Production_Order_ID"].notna()
        & exceptions["Material_ID"].notna()
    ].copy()
    if material.empty:
        return material
    keys = [column for column in DEMAND_IDENTITY if column in material]
    return material.sort_values("Exception_ID", kind="stable").drop_duplicates(keys)


def build_order_summary(exceptions: pd.DataFrame, orders: pd.DataFrame) -> pd.DataFrame:
    columns = ["Sales_Order_ID", "Sales_Order_Item", "Product_ID", "Product_Description", "Requested_Delivery_Date", "Plant",
               "Related_Production_Orders", "Exception_Types", "Affected_Materials", "Total_Shortage_Quantity",
               "Highest_Priority", "Responsible_Roles", "Workflow_Status"]
    if exceptions.empty:
        return pd.DataFrame(columns=columns)
    merged = exceptions[exceptions["Sales_Order_ID"].notna()].copy()
    if merged.empty:
        return pd.DataFrame(columns=columns)
    lookup = orders.copy()
    lookup["Sales_Order_ID"] = lookup["Sales_Order_ID"].astype(str)
    lookup["Sales_Order_Item"] = lookup["Sales_Order_Item"].astype(str)
    grouped = merged.groupby(["Sales_Order_ID", "Sales_Order_Item"], dropna=False).agg(
        Product_ID=("Product_ID", _join), Plant=("Plant", _join),
        Related_Production_Orders=("Production_Order_ID", _join), Exception_Types=("Exception_Type", _join),
        Affected_Materials=("Material_ID", lambda s: len({str(x) for x in s.dropna()})),
        Highest_Priority=("Priority", _highest),
        Responsible_Roles=("Responsible_Role", _join), Workflow_Status=("Workflow_Status", _join),
    ).reset_index()
    quantities = _unique_material_demands(merged)
    shortage = (
        quantities.groupby(["Sales_Order_ID", "Sales_Order_Item"], dropna=False)["Shortage_Quantity"]
        .sum().rename("Total_Shortage_Quantity").reset_index()
        if not quantities.empty else
        pd.DataFrame(columns=["Sales_Order_ID", "Sales_Order_Item", "Total_Shortage_Quantity"])
    )
    grouped = grouped.merge(shortage, on=["Sales_Order_ID", "Sales_Order_Item"], how="left")
    grouped["Total_Shortage_Quantity"] = grouped["Total_Shortage_Quantity"].fillna(0.0)
    grouped["Sales_Order_ID"] = grouped["Sales_Order_ID"].astype(str)
    grouped["Sales_Order_Item"] = grouped["Sales_Order_Item"].astype(str)
    if "Product_Description" not in lookup:
        lookup["Product_Description"] = lookup["Product_ID"]
    grouped = grouped.merge(lookup[["Sales_Order_ID", "Sales_Order_Item", "Product_Description", "Requested_Delivery_Date"]],
                            on=["Sales_Order_ID", "Sales_Order_Item"], how="left")
    return grouped[columns]


def build_material_summary(exceptions: pd.DataFrame) -> pd.DataFrame:
    columns = ["Material_ID", "Material_Description", "Material_Category", "Plant", "Affected_Orders", "Affected_Production_Orders", "Exception_Types",
               "Total_Required_Quantity", "Total_Shortage_Quantity", "Earliest_Need_Date", "Highest_Priority",
               "Responsible_Roles", "Workflow_Status"]
    material = exceptions[exceptions["Material_ID"].notna()].copy()
    if material.empty:
        return pd.DataFrame(columns=columns)
    if "Material_Description" not in material: material["Material_Description"] = material["Material_ID"]
    if "Material_Category" not in material: material["Material_Category"] = "Not classified"
    dimensions = ["Material_ID", "Material_Description", "Material_Category", "Plant"]
    grouped = material.groupby(dimensions, dropna=False).agg(
        Affected_Orders=("Sales_Order_ID", lambda s: len({str(x) for x in s.dropna()})),
        Affected_Production_Orders=("Production_Order_ID", lambda s: len({str(x) for x in s.dropna()})),
        Exception_Types=("Exception_Type", _join), Earliest_Need_Date=("Material_Need_Date", "min"),
        Highest_Priority=("Priority", _highest), Responsible_Roles=("Responsible_Role", _join),
        Workflow_Status=("Workflow_Status", _join),
    ).reset_index()
    quantities = _unique_material_demands(material)
    if not quantities.empty:
        quantity_totals = quantities.groupby(["Material_ID", "Plant"], dropna=False).agg(
            Total_Required_Quantity=("Required_Quantity", "sum"),
            Total_Shortage_Quantity=("Shortage_Quantity", "sum"),
        ).reset_index()
        grouped = grouped.merge(quantity_totals, on=["Material_ID", "Plant"], how="left")
    else:
        grouped["Total_Required_Quantity"] = 0.0
        grouped["Total_Shortage_Quantity"] = 0.0
    grouped[["Total_Required_Quantity", "Total_Shortage_Quantity"]] = grouped[
        ["Total_Required_Quantity", "Total_Shortage_Quantity"]
    ].fillna(0.0)
    return grouped[columns]
