# Deterministic Exception Rules

| Type | Rule | Role |
|---|---|---|
| `MATERIAL_SHORTAGE` | `Shortage_Quantity > 0` | Procurement |
| `UNSCHEDULED_ORDER` | Open positive order without an active or completed linked production order | Production Planning |
| `PRODUCTION_BACKLOG` | Active incomplete production order with positive remaining quantity and planned end before analysis date | Production Planning |
| `OVERDUE_INCOMING_PO` | Active open undeleted/uncompleted PO receipt dated before analysis date | Procurement |
| `LATE_INCOMING_SUPPLY` | Matching material/plant/unit PO receipt after material need date | Procurement |
| `OVERDUE_INCOMING_SUPPLY` | Order material demand has matching material/plant/unit open PO quantity dated before analysis date | Procurement |
| `PLANNED_COMPLETION_AFTER_REQUESTED_DELIVERY` | Active linked production order has planned end after the sales-order requested delivery date | Production Planning |
| `ZERO_SCHEDULE_BUFFER` | Active linked production order has planned end equal to requested delivery date | Production Planning |

Exception IDs are SHA-256-derived from type, analysis date, and source identity. Allocation is stable and pool-based; inventory and PO quantities are consumed once and never cross plant or unit. Covered late/overdue supply and zero-buffer signals are classified as `MONITOR`; material shortages and production backlog are direct blocking signals. PO relationships are material-plant-pool relationships, not direct sales-order pegging. Streamlit and the LLM do not participate in these rules.
