# Demonstration Guide

1. Start Streamlit and upload a valid five-sheet ERP workbook.
2. Set the analysis date to 25 September 2026, validate, and run deterministic analysis.
3. Use Overview to explain the primary KPIs, secondary planning signals, and complementary charts.
4. In My Orders, search an order and choose a shortage or Pending Scheduling view.
5. In My Materials, inspect inventory, incoming allocation, shortages, supplier context, and priority.
6. In AI Planning Copilot, select a risky order, inspect the payload, enter an OpenRouter API key in the password field, and generate an action plan only when the cost is approved. The key remains session-only.
7. Confirm `Human Review Required` and `NOT_EXECUTED`; export results from the collapsed Export Results area.
8. In Exception Workflow, update a human review status and confirm that it is marked session-only and absent from the AI payload.

Pending Scheduling remains a deterministic planning-completeness exception, but it is excluded from material and AI action-plan views because no verified production requirement, capacity, routing, or planning-version evidence exists. Nothing is sent, assigned, purchased, rescheduled, or written to ERP.
