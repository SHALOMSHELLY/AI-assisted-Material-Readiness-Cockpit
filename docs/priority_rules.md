# Priority Rules

Priority is assigned by an independent, testable Python function. The LLM may explain the result but cannot change it. Rules are applied in the order below.

P0 represents a validation Data Error. Validation failure blocks shortage calculation, so successfully generated shortage rows use P1 through P4 only.

| Priority | Rule ID | Condition | Meaning |
|---|---|---|---|
| Data Error | P0 | Missing data, unit mismatch, failed relationship, or rule conflict prevents reliable calculation | Block deterministic analysis for the uploaded workbook and request data correction |
| Critical | P1 | `Shortage > 0` and `Days Until Planned Start <= 2` | Shortage exists and production starts within two days or is overdue |
| High | P2 | `Shortage > 0` and `3 <= Days Until Planned Start <= 7` | Shortage exists and production starts in 3–7 days |
| Medium | P3A | `Shortage > 0` and `Days Until Planned Start > 7` | Shortage exists and production starts in more than 7 days |
| Medium | P3B | `Shortage = 0` and a required latest receipt is within one day before start | Supply is sufficient but depends on a near-start receipt |
| Low | P4 | `Shortage = 0` and the demand is not dependent on a near-start receipt | Current supply is sufficient |

`Days Until Planned Start = Planned Start Date - Analysis Date`

A negative value means the planned start date has passed and still satisfies `<= 2`. For P3B, a required receipt is the latest allocated PO receipt whose removal would create a shortage. P3B does not apply when no PO supply is allocated.

