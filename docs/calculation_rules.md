# Calculation Rules

## Scope

Version 1 supports single-level BOMs only. A material may be aggregated only within the same plant and unit, with no unit conversion. The deterministic Python engine performs all calculations.

## Demand

`Material Need Date = Planned Start Date`

`Expected Remaining Quantity = max(0, Total Quantity - Confirmed Yield Quantity)`

`Material Requirement = Remaining Production Quantity / BOM Base Quantity × BOM Component Quantity`

Only `CREATED`, `RELEASED`, and `PARTIALLY_CONFIRMED` production orders with a valid `Remaining_Quantity > 0` create future demand. Demand uses remaining quantity to avoid recounting completed yield. The production-order unit must equal the BOM base unit. A zero-remaining-quantity order does not require a BOM.

## Inventory

`Unrestricted Inventory = SUM(Quantity where Stock_Type = UNRESTRICTED for the same Material_ID and Plant)`

`Usable Inventory = max(0, Unrestricted Inventory - Safety Stock)`

UNRESTRICTED stock is summed across storage locations before the material+plant safety stock is deducted once. Inconsistent safety-stock values are a Data Error.

## Incoming supply

`Expected Open Quantity = max(0, Ordered Quantity - Received Quantity)`

A PO schedule line is eligible only when all conditions hold:

- `PO_Status` is `OPEN` or `PARTIALLY_RECEIVED`;
- `Deletion_Flag = FALSE`;
- `Completely_Delivered_Flag = FALSE`;
- `Open_Quantity > 0`;
- `Analysis_Date <= Expected_Receipt_Date <= Material_Need_Date`;
- material, plant, and unit match.

Use `Open_Quantity`, not original ordered quantity. A receipt on the need date is eligible. A later receipt is Late Incoming and cannot be allocated to that demand.

A positive open PO line dated before `Analysis_Date` is Overdue Incoming. It is excluded from eligible supply and allocation and is recorded in `Overdue_Incoming_Quantity` and `Overdue_PO_Lines`. A receipt dated on the analysis date is not overdue.

## Allocation

Production demand is processed by:

1. `Planned_Start_Date` ascending;
2. `Production_Order_ID` ascending;
3. `Production_Order_Item` ascending.

For each material+plant+unit supply pool, usable inventory is allocated first. Eligible PO supply is then allocated in stable order by expected receipt date, PO ID, item, and schedule line. Inventory and PO open quantity may each be consumed only once.

`Total Available Allocated = Inventory Allocated + Incoming PO Allocated`

`Shortage Quantity = max(0, Required Quantity - Total Available Allocated)`

Audit output retains supply before allocation, remaining inventory, exact used PO schedule lines, overdue quantity and details, the next remaining receipt date, priority rule ID, and explanations. `Next_Receipt_Date` is the earliest non-overdue date among PO records that still have open quantity after the current allocation.

## Date and precision assumptions

Tests use the fixed `Analysis_Date = 2026-09-25`, never the computer date. Date comparisons are calendar-day based with no time-zone component. Calculations preserve source numeric precision; UI formatting must not alter fact values.

