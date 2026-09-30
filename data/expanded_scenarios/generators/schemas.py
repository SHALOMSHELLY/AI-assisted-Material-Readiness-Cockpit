"""Workbook schema copied from the current ERP data dictionary."""

SHEET_COLUMNS: dict[str, list[str]] = {
    "Orders": ["Sales_Order_ID", "Sales_Order_Item", "Customer_ID", "Product_ID", "Product_Description", "Product_Family", "Requested_Quantity", "Quantity_Unit", "Requested_Delivery_Date", "Plant", "Order_Status"],
    "BOM": ["BOM_ID", "BOM_Item_ID", "Parent_Product_ID", "Plant", "BOM_Usage", "Alternative_BOM", "Base_Quantity", "Base_Quantity_Unit", "Component_Material_ID", "Component_Material_Description", "Material_Category", "Component_Quantity", "Component_Unit", "Valid_From", "Valid_To"],
    "Inventory": ["Material_ID", "Plant", "Storage_Location", "Stock_Type", "Quantity", "Base_Unit", "Safety_Stock", "Snapshot_Date"],
    "Incoming_PO": ["PO_ID", "PO_Item", "Schedule_Line", "Material_ID", "Plant", "Storage_Location", "Ordered_Quantity", "Received_Quantity", "Open_Quantity", "Quantity_Unit", "Expected_Receipt_Date", "PO_Status", "Deletion_Flag", "Completely_Delivered_Flag", "Supplier_ID", "Supplier_Name"],
    "Production_Orders": ["Production_Order_ID", "Production_Order_Item", "Source_Sales_Order_ID", "Source_Sales_Order_Item", "Product_ID", "Plant", "Total_Quantity", "Confirmed_Yield_Quantity", "Remaining_Quantity", "Quantity_Unit", "Planned_Start_Date", "Planned_End_Date", "Order_Status"],
}

REQUIRED_SHEETS = tuple(SHEET_COLUMNS)
