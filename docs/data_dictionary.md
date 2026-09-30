# Data Dictionary

Identifiers are read as text to preserve leading zeros. Quantities are numeric and dates are Excel dates. Required fields are mandatory. Version 1 performs no automatic unit conversion.

## Workbook structure

The workbook must contain exactly named required worksheets: `Orders`, `BOM`, `Inventory`, `Incoming_PO`, and `Production_Orders`. Additional worksheets are allowed but excluded from analysis and reported as warnings.

## Orders

Unique key: `Sales_Order_ID + Sales_Order_Item`.

| Field | Type | Required | Rule |
|---|---|---:|---|
| Sales_Order_ID | Text | Yes | Sales-order identifier |
| Sales_Order_Item | Text | Yes | Sales-order item |
| Customer_ID | Text | No | Customer identifier |
| Product_ID | Text | Yes | Ordered product |
| Requested_Quantity | Number | Yes | Greater than zero |
| Quantity_Unit | Text | Yes | Order quantity unit |
| Requested_Delivery_Date | Date | Yes | Requested delivery date |
| Plant | Text | Yes | Responsible plant |
| Order_Status | Text | Yes | `OPEN`, `COMPLETED`, or `CANCELLED`; only `OPEN` is tracked |

## BOM

Unique key: `BOM_ID + BOM_Item_ID`.

| Field | Type | Required | Rule |
|---|---|---:|---|
| BOM_ID | Text | Yes | BOM identifier |
| BOM_Item_ID | Text | Yes | BOM item |
| Parent_Product_ID | Text | Yes | Parent product |
| Plant | Text | Yes | Applicable plant |
| BOM_Usage | Text | Yes | Version 1 default: `1` |
| Alternative_BOM | Text | Yes | Version 1 default: `01` |
| Base_Quantity | Number | Yes | Greater than zero |
| Base_Quantity_Unit | Text | Yes | Parent-product unit |
| Component_Material_ID | Text | Yes | Component material |
| Component_Quantity | Number | Yes | Quantity per base quantity; greater than zero |
| Component_Unit | Text | Yes | Component unit |
| Valid_From | Date | Yes | Valid-from date |
| Valid_To | Date | No | Blank means no predefined end date |

A BOM row is effective on the material need date when `Valid_From <= Material_Need_Date` and `Valid_To` is blank or `Valid_To >= Material_Need_Date`.

## Inventory

Unique key: `Material_ID + Plant + Storage_Location + Stock_Type`. Safety stock is controlled at `Material_ID + Plant`.

| Field | Type | Required | Rule |
|---|---|---:|---|
| Material_ID | Text | Yes | Material identifier |
| Plant | Text | Yes | Plant |
| Storage_Location | Text | Yes | Storage location |
| Stock_Type | Text | Yes | Only `UNRESTRICTED` is usable |
| Quantity | Number | Yes | Non-negative stock quantity |
| Base_Unit | Text | Yes | Base unit |
| Safety_Stock | Number | Yes | Non-negative; consistent at material+plant |
| Snapshot_Date | Date | Yes | Identical across all Inventory rows and not later than `Analysis_Date` |

If a currently effective BOM component has no same-plant Inventory row, the system warns, uses zero for unrestricted inventory, safety stock, and usable inventory, and continues calculation.

## Incoming_PO

Unique key: `PO_ID + PO_Item + Schedule_Line`.

| Field | Type | Required | Rule |
|---|---|---:|---|
| PO_ID | Text | Yes | Purchase-order identifier |
| PO_Item | Text | Yes | PO item |
| Schedule_Line | Text | Yes | Schedule line |
| Material_ID | Text | Yes | Purchased material |
| Plant | Text | Yes | Receiving plant |
| Storage_Location | Text | Yes | Expected storage location |
| Ordered_Quantity | Number | Yes | Non-negative |
| Received_Quantity | Number | Yes | Non-negative |
| Open_Quantity | Number | Yes | `max(0, Ordered_Quantity - Received_Quantity)` |
| Quantity_Unit | Text | Yes | PO quantity unit |
| Expected_Receipt_Date | Date | Yes | Expected receipt date |
| PO_Status | Text | Yes | `OPEN`, `PARTIALLY_RECEIVED`, `COMPLETED`, or `CANCELLED` |
| Deletion_Flag | Boolean | Yes | Excel Boolean TRUE/FALSE or numeric 1/0; text values are rejected |
| Completely_Delivered_Flag | Boolean | Yes | Excel Boolean TRUE/FALSE or numeric 1/0; text values are rejected |
| Supplier_ID | Text | No | Supplier identifier |

Rows unrelated to current effective BOM demand are ignored rather than treated as Data Errors. Before matching and unit validation, the system also ignores completed, cancelled, deleted, completely delivered, and zero-open-quantity rows.

## Production_Orders

Unique key: `Production_Order_ID + Production_Order_Item`.

| Field | Type | Required | Rule |
|---|---|---:|---|
| Production_Order_ID | Text | Yes | Production-order identifier |
| Production_Order_Item | Text | Yes | Production-order item |
| Source_Sales_Order_ID | Text | Conditional | Blank together with source item for make-to-stock, or populated with source item |
| Source_Sales_Order_Item | Text | Conditional | When populated, the composite source key must exist in Orders |
| Product_ID | Text | Yes | Product to produce |
| Plant | Text | Yes | Production plant |
| Total_Quantity | Number | Yes | Non-negative |
| Confirmed_Yield_Quantity | Number | Yes | Non-negative |
| Remaining_Quantity | Number | Yes | `max(0, Total_Quantity - Confirmed_Yield_Quantity)` |
| Quantity_Unit | Text | Yes | Production quantity unit |
| Planned_Start_Date | Date | Yes | Planned start and material need date |
| Planned_End_Date | Date | Yes | Planned end date |
| Order_Status | Text | Yes | Allowed values are defined by validation rules |

Only `CREATED`, `RELEASED`, and `PARTIALLY_CONFIRMED` orders with a valid positive `Remaining_Quantity` create BOM, inventory, and PO-supply relationships. A zero-remaining order does not require a BOM match.

