# SAP-Informed Field Mapping

This mapping explains the business-object inspiration and does not claim one-to-one equivalence with SAP tables or APIs. Field names are designed for a course prototype and an Excel-based demonstration.

| Prototype sheet | SAP-informed object | Retained idea | Simplification |
|---|---|---|---|
| Orders | Sales Order Item | Order/item, product, requested quantity/date, plant, status | Omits partners, pricing, and delivery schedules; tracks OPEN only |
| BOM | Bill of Material | Parent, component, base quantity, usage, alternative, validity | Single-level only; omits change numbers, item categories, and scrap |
| Inventory | Material Stock | Material, plant, storage location, stock type, quantity | Safety stock is embedded but interpreted at material+plant; no batch or special stock |
| Incoming_PO | Purchase Order Item and Schedule Line | PO/item/schedule line, ordered/received/open quantity, receipt date, flags | Flattens item and schedule line; no goods-receipt documents or confirmation history |
| Production_Orders | Production Order | Product, plant, total/yield/remaining, dates, status | Uses remaining quantity for future demand; does not reconstruct issues, confirmations, or actual consumption |

## Relationship choices

SAP business objects normally have more complex keys, organizational levels, and status handling. This prototype explicitly uses composite order/item and PO/item/schedule-line keys and requires plant and unit in material joins to prevent incorrect aggregation.

## Official references

- [Sales Order Item](https://help.sap.com/docs/SAP_S4HANA_CLOUD/c0c54048d35849128be8e872df5bea6d/4cb98651bcae44c3a2924681ca194988.html)
- [Sales Order Item API](https://help.sap.com/docs/SAP_S4HANA_CLOUD/03c04db2a7434731b7fe21dca77440da/32dc44581efca007e10000000a441470.html)
- [Bill of Material](https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/9f047b05da4545ca8f9ebfc22acefd06/ac29c05833e44980ab6b236e409f2429.html)
- [Material Stock](https://help.sap.com/docs/SAP_S4HANA_CLOUD/3f57e7df4a114edabffe8b2d581a59ed/f68f51a4dc2e46779877a10a301d9138.html)
- [Purchase Order Schedule Line](https://help.sap.com/docs/SAP_S4HANA_CLOUD/bb9f1469daf04bd894ab2167f8132a1a/6b56d657867b6264e10000000a4450e5.html)
- [Purchase Order Item](https://help.sap.com/docs/SAP_S4HANA_CLOUD/bb9f1469daf04bd894ab2167f8132a1a/3c55df577ec43528e10000000a441470.html)
- [Production Order](https://help.sap.com/docs/SAP_S4HANA_CLOUD/d35113ee62644d3abee1aaec148291d9/e76b570c36764ae9a1cc4747a3c144b7.html)

