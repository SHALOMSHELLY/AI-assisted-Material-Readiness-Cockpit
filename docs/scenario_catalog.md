# Scenario Catalog

The machine-readable authority is `data/expanded_scenarios/scenario_catalog.json`; it records story, rules, actual row counts, expected exceptions, paths, and demo recommendation.

- Small: S01–S09, 12–16 sales orders, 6–8 products, 20–25 components, 10–14 production orders, two plants.
- Medium: M01–M08, 62–90 sales orders, 19–26 products, 59–87 components, 51–72 production orders, three plants.
- Large: L01–L08, 222–306 sales orders, 46–60 products, 163–219 components, 198–268 production orders, four plants.

The 25 primary themes span balanced/no-shortage control, shortages, late/overdue supply, shared-material competition, safety stock, plant/unit isolation, schedule lines, partial receipts, sequencing/ties, bottlenecks, unscheduled/backlog, excluded POs/inventory, BOM effectivity, storage locations, and portfolio performance. All workbooks also contain a mixed planning-day context.

Blocking validation cases belong in separate V01–V05 fixtures and are not counted in these 25 formal workbooks.
