"""Deterministic ERP snapshot builder; independent of production analysis code."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import timedelta
from .common import ANALYSIS_DATE, Scenario, bom, deterministic_permutation, empty_sheets, inventory, order, po, production
from .master_data import component_master, product_master

@dataclass(frozen=True)
class PortfolioSize:
    orders: int; products: int; materials: int; production_orders: int; po_lines: int; plants: tuple[str, ...]

THEMES = (
    "Balanced Operations", "No-Shortage Control", "Inventory Shortage", "Late Incoming Supply", "Overdue Purchase Orders",
    "Shared Material Competition", "Safety Stock Boundary", "Multi-Plant Isolation", "Multi-Unit Isolation",
    "Multiple PO Schedule Lines", "Partial Receipt", "Production Sequence", "Same-Day Tie Breaking",
    "Multi-Component Bottleneck", "One Material Affecting Multiple Orders", "Unscheduled Orders", "Production Backlog",
    "Mixed Planning Day", "Cancelled PO Exclusion", "Deleted PO Exclusion", "Completed PO Exclusion",
    "Non-Unrestricted Inventory Exclusion", "BOM Effectivity", "Multiple Storage Locations", "Large Portfolio Performance",
)

def build_portfolio(scenario_id: str, category: str, theme_index: int, size: PortfolioSize) -> Scenario:
    """Build one valid, reproducible manufacturing planning snapshot."""
    sheets = empty_sheets(); theme = THEMES[theme_index]
    products = [product_master(i) for i in range(size.products)]
    materials = [component_master(i) for i in range(size.materials)]
    product_plants = {code: size.plants[i % len(size.plants)] for i, (code, _, _) in enumerate(products)}
    for i in range(size.orders):
        code, description, family = products[(i + theme_index) % len(products)]; plant = product_plants[code]
        sheets["Orders"].append(order(theme_index * 10000 + i + 1, code, plant, 2 + i % 9, description, family))
    for p_index, (product, _, _) in enumerate(products):
        plant = product_plants[product]; component_count = 3 + (p_index + theme_index) % 4; chosen = set()
        for c_index in range(component_count):
            span = max(8, size.materials // 3)
            index = ((p_index * 11 + c_index * 7 + theme_index) % span if c_index < 2 else (p_index * 13 + c_index * 17 + theme_index) % size.materials)
            while index in chosen: index = (index + 1) % size.materials
            chosen.add(index); material, description, material_category = materials[index]
            sheets["BOM"].append(bom(product, material, plant, 1 + (p_index + c_index) % 3, 10 * (c_index + 1), description, material_category))
    # Guarantee that the declared component portfolio is represented at least once.
    used_materials = {row["Component_Material_ID"] for row in sheets["BOM"]}
    for m_index, (material, description, material_category) in enumerate(materials):
        if material in used_materials: continue
        product, _, _ = products[m_index % len(products)]; plant = product_plants[product]
        sheets["BOM"].append(bom(product, material, plant, 1 + m_index % 3, 1000 + m_index, description, material_category))
    for i in range(size.production_orders):
        source = sheets["Orders"][i]; start = -4 if i == 0 or (theme == "Production Backlog" and i < 4) else 1 + (i * 5 + theme_index) % 24
        prod = production(theme_index * 10000 + i + 1, source["Product_ID"], 1 + i % 7, start, source["Plant"], status="PARTIALLY_CONFIRMED" if i % 13 == 0 else "RELEASED", confirmed=i % 3)
        prod["Source_Sales_Order_ID"] = source["Sales_Order_ID"]; prod["Source_Sales_Order_Item"] = source["Sales_Order_Item"]
        if start < 0: prod["Planned_End_Date"] = ANALYSIS_DATE - timedelta(days=1 + i % 3)
        sheets["Production_Orders"].append(prod)
    demo_source = sheets["Orders"][0]
    demo_materials = {row["Component_Material_ID"] for row in sheets["BOM"] if row["Parent_Product_ID"] == demo_source["Product_ID"] and row["Plant"] == demo_source["Plant"]}
    for m_index, (material, _, _) in enumerate(materials):
        for plant_index, plant in enumerate(size.plants):
            demo_risk = scenario_id == "M08" and material in demo_materials and plant == demo_source["Plant"]
            risk = demo_risk or (m_index < 8 and (m_index + theme_index + plant_index) % 3 == 0)
            quantity = (0 if demo_risk else 2 + (m_index * 19 + plant_index * 7 + theme_index) % 18) if risk else (80 + (m_index * 23) % 140)
            safety = 2 + m_index % 4
            sheets["Inventory"].append(inventory(material, quantity, plant, "0001", safety))
            if (m_index + plant_index) % 3 == 0: sheets["Inventory"].append(inventory(material, 5 + m_index % 12, plant, "0002", safety))
            if (m_index + plant_index) % 11 == 0: sheets["Inventory"].append(inventory(material, 30, plant, "Q001", safety, "QUALITY_INSPECTION"))
    demanded = [(material, plant) for material, _, _ in materials for plant in size.plants]
    for i in range(size.po_lines):
        material, plant = demanded[(i * 17 + theme_index) % len(demanded)]; status, deleted, delivered = "OPEN", False, False
        if i % 41 == 0: status = "CANCELLED"
        elif i % 43 == 0: deleted = True
        elif i % 47 == 0: status, delivered = "COMPLETED", True
        offset = -2 if i % 37 == 1 else 2 + (i * 7 + theme_index) % 30
        if scenario_id == "M08" and material in demo_materials and plant == demo_source["Plant"]: offset = 28
        quantity = 8 + (i * 11) % 34
        received = quantity if delivered else (quantity // 3 if i % 9 == 0 and status == "OPEN" else 0)
        if received: status = "PARTIALLY_RECEIVED"
        sheets["Incoming_PO"].append(po(theme_index * 10000 + i + 1, material, quantity, offset, plant, received=received, status=status, deleted=deleted, delivered=delivered, item=str(10 + i % 4 * 10), schedule=str(1 + i % 3)))
    for name in sheets: sheets[name] = deterministic_permutation(sheets[name], 31 + theme_index + len(name))
    return Scenario(scenario_id, category, theme, (theme.lower().replace(" ", "-"), "stable-allocation", "synthetic-erp", "independent-oracle"), sheets)
