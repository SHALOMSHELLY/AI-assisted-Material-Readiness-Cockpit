"""Typed row builders shared by all expanded scenarios."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from .schemas import REQUIRED_SHEETS
from .master_data import SUPPLIERS

ANALYSIS_DATE = date(2026, 9, 25)
Row = dict[str, Any]
Sheets = dict[str, list[Row]]


@dataclass(frozen=True)
class Scenario:
    """A workbook definition plus immutable catalog metadata."""

    scenario_id: str
    category: str
    purpose: str
    covered_rules: tuple[str, ...]
    sheets: Sheets
    extra_sheets: dict[str, list[Row]] | None = None
    omitted_sheets: tuple[str, ...] = ()

    @property
    def row_counts(self) -> dict[str, int]:
        return {name: len(self.sheets[name]) for name in REQUIRED_SHEETS if name not in self.omitted_sheets}


def empty_sheets() -> Sheets:
    return {name: [] for name in REQUIRED_SHEETS}


def order(i: int, product: str, plant: str = "1010", quantity: float = 10, description: str | None = None, family: str | None = None) -> Row:
    return {"Sales_Order_ID": f"SOA{i:07d}", "Sales_Order_Item": "10", "Customer_ID": f"CUST{i % 37:03d}", "Product_ID": product, "Product_Description": description or product, "Product_Family": family or "Industrial Controls", "Requested_Quantity": quantity, "Quantity_Unit": "EA", "Requested_Delivery_Date": ANALYSIS_DATE + timedelta(days=5 + i % 24), "Plant": plant, "Order_Status": "OPEN"}


def bom(product: str, material: str, plant: str = "1010", component_quantity: float = 1, item: int = 10, description: str | None = None, category: str | None = None) -> Row:
    return {"BOM_ID": f"BOM-{plant}-{product}", "BOM_Item_ID": str(item), "Parent_Product_ID": product, "Plant": plant, "BOM_Usage": "1", "Alternative_BOM": "01", "Base_Quantity": 1, "Base_Quantity_Unit": "EA", "Component_Material_ID": material, "Component_Material_Description": description or material, "Material_Category": category or "Other", "Component_Quantity": component_quantity, "Component_Unit": "EA", "Valid_From": date(2026, 1, 1), "Valid_To": None}


def inventory(material: str, quantity: float, plant: str = "1010", location: str = "0001", safety: float = 0, stock_type: str = "UNRESTRICTED") -> Row:
    return {"Material_ID": material, "Plant": plant, "Storage_Location": location, "Stock_Type": stock_type, "Quantity": quantity, "Base_Unit": "EA", "Safety_Stock": safety, "Snapshot_Date": ANALYSIS_DATE}


def po(i: int, material: str, quantity: float, receipt_offset: int, plant: str = "1010", *, received: float = 0, status: str = "OPEN", deleted: bool = False, delivered: bool = False, item: str = "10", schedule: str = "1") -> Row:
    supplier_id, supplier_name = SUPPLIERS[i % len(SUPPLIERS)]
    return {"PO_ID": f"POA{i:07d}", "PO_Item": item, "Schedule_Line": schedule, "Material_ID": material, "Plant": plant, "Storage_Location": "0001", "Ordered_Quantity": quantity, "Received_Quantity": received, "Open_Quantity": max(0, quantity - received), "Quantity_Unit": "EA", "Expected_Receipt_Date": ANALYSIS_DATE + timedelta(days=receipt_offset), "PO_Status": status, "Deletion_Flag": deleted, "Completely_Delivered_Flag": delivered, "Supplier_ID": supplier_id, "Supplier_Name": supplier_name}


def production(i: int, product: str, remaining: float, start_offset: int, plant: str = "1010", *, status: str = "RELEASED", item: str = "10", confirmed: float = 0) -> Row:
    total = remaining + confirmed
    return {"Production_Order_ID": f"PRX{i:06d}", "Production_Order_Item": item, "Source_Sales_Order_ID": None, "Source_Sales_Order_Item": None, "Product_ID": product, "Plant": plant, "Total_Quantity": total, "Confirmed_Yield_Quantity": confirmed, "Remaining_Quantity": remaining, "Quantity_Unit": "EA", "Planned_Start_Date": ANALYSIS_DATE + timedelta(days=start_offset), "Planned_End_Date": ANALYSIS_DATE + timedelta(days=start_offset + 2), "Order_Status": status}


def deterministic_permutation(rows: list[Row], salt: int = 17) -> list[Row]:
    """Shuffle without random state; stable across Python versions and machines."""

    return sorted(rows, key=lambda row: sum(ord(ch) for ch in repr(sorted(row.items()))) * salt % 1000003)
