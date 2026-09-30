# Data Design

All scenarios represent Apex Industrial Controls and retain exactly five required sheets. Orders and BOM may include product/material descriptions and categories; Incoming_PO may include supplier name. These are optional presentation fields and do not change the required legacy schema.

Generation is formula-driven with stable identifiers and no ambient random state. Relationships, units, plants, dates, BOM effectivity, inventory snapshots, PO flags/status, partial receipts, production links, multiple locations, unusable stock, shared materials, and normal/exception mixtures are created before either engine runs. The workbook generator never imports production analysis code.

The independent Oracle separately implements the documented allocation order. Frozen JSON includes row keys, required quantity, inventory and incoming allocation, shortage, priority/rule, exception counts, unscheduled/backlog/late/overdue counts, descriptions, and categories.
