# Validation Rules

## Validation behavior

Validation outcomes are Data Error, Warning, or Ignored.

A Data Error identifies the worksheet, Excel row, field, invalid value, error code, English message, and repair guidance. It blocks the affected calculation; structural workbook errors block the whole analysis. A Warning calls for attention but permits calculation under a documented safe default. Ignored means a row is outside the current analysis scope and is excluded with its count and reason reported. The UI must not expose Python stack traces.

## Checks

1. The file is readable and uses a supported Excel format.
2. All five required sheets exist with exact names; additional sheets are ignored and reported as warnings.
3. Every required column exists.
4. Required values are not blank.
5. Composite keys are unique, including the Inventory key `Material_ID + Plant + Storage_Location + Stock_Type`.
6. Quantity fields are numeric.
7. Non-negative quantities are not below zero.
8. Requested quantity, BOM base quantity, and BOM component quantity are greater than zero.
9. Dates are valid.
10. BOM validity ranges satisfy `Valid_From <= Valid_To` when `Valid_To` is present.
11. Production dates satisfy `Planned_Start_Date <= Planned_End_Date`.
12. Required material, product, plant, and unit values are present.
13. Statuses and stock types belong to allowed sets.
14. Production-order unit matches BOM base unit.
15. Component unit matches related inventory and participating PO units.
16. Exactly one effective BOM exists for each participating product and material need date.
17. A missing same-plant Inventory row for an effective BOM component creates a Warning and zero-inventory default, not a Data Error.
18. PO rows unrelated to current effective BOM demand are Ignored.
19. `Open_Quantity = max(0, Ordered_Quantity - Received_Quantity)`.
20. `Remaining_Quantity = max(0, Total_Quantity - Confirmed_Yield_Quantity)`.
21. Safety stock is consistent within material+plant.
22. Source sales-order ID and item are both blank or both populated; populated composite keys must exist in Orders.
23. PO status and flags are internally consistent.
24. Only participating production-order statuses create demand.
25. A component that is also an effective parent product in scope triggers Unsupported Scope.
26. Plants and units are never pooled across keys.
27. All Inventory rows use one `Snapshot_Date`.
28. `Snapshot_Date` is not later than `Analysis_Date`.
29. PO flags accept Excel Boolean TRUE/FALSE or numeric 1/0; text `"TRUE"` and `"FALSE"` are Data Errors.
30. Rows grouped by `BOM_ID + BOM_Usage + Alternative_BOM` have consistent parent product, plant, base quantity, and base unit.
31. A participating positive-open PO row dated before `Analysis_Date` creates an Overdue Incoming Warning and is excluded from eligible supply.

## Non-blocking outcomes

- Additional worksheets are ignored and named in warnings.
- Missing Inventory for an effective BOM component uses a documented zero-inventory default.
- PO rows unrelated to effective demand enter no supply pool.
- Completed, cancelled, deleted, completely delivered, and zero-open-quantity PO rows are ignored before demand matching and unit validation.
- A relevant active PO row before the analysis date produces `OVERDUE_INCOMING_PO`; a row on the analysis date may participate normally.

## BOM header consistency

Every component row under the same `BOM_ID + BOM_Usage + Alternative_BOM` must share parent product, plant, base quantity, and base unit. A conflict produces `INCONSISTENT_BOM_HEADER` and blocks calculation.

## Demand relationship scope

Only production orders in `ACTIVE_PRODUCTION_ORDER_STATUSES` with valid positive `Remaining_Quantity` create BOM demand relationships. Zero-remaining orders require no BOM, Inventory, or Incoming PO match.

Multilevel-BOM detection starts from the effective BOM selected for a participating production order. A child BOM must belong to the same plant and be effective on the same need date. Other-plant, expired, or unrelated BOMs do not trigger a multilevel-BOM error.

## Status and flag consistency

`COMPLETED` and `CANCELLED` PO rows are not future supply. Deleted or completely delivered rows are also excluded. Conflicts such as `OPEN` with a true completely-delivered flag, or `COMPLETED` with positive open quantity, are Data Errors.

