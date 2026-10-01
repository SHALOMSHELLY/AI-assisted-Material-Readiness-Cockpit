# Data Explainer

## Purpose and privacy

All checked-in ERP-style workbooks are synthetic and describe the fictional manufacturer Apex Industrial Controls. They contain no real company, customer, supplier, or employee records.

## Workbook structure

Each generated workbook contains five related sheets: `Orders`, `BOM`, `Inventory`, `Incoming_PO`, and `Production_Orders`. Their fields and relationships are documented in [Data Design](../docs/data_design.md) and [Data Dictionary](../docs/data_dictionary.md).

## Scenario set

`expanded_scenarios/generated` contains 25 reproducible workbooks: 9 small, 8 medium, and 8 large scenarios. [Scenario Catalog](../docs/scenario_catalog.md) explains the intended coverage. `scenario_catalog.json` provides the machine-readable catalog.

## Expected results

`expanded_scenarios/expected/scenarios` contains independent expected results for each workbook. `oracle_summary.csv` summarizes the comparison. The Oracle does not import the production shortage, exception, or priority engines.

## Regeneration

Run the following commands from the repository root:

```powershell
python data/expanded_scenarios/generators/generate_expanded_workbooks.py --overwrite
python scripts/build_scenario_artifacts.py
python scripts/evaluate_oracles.py
```

The deterministic acceptance target is 25/25 workbooks with no missing rows, unexpected rows, quantity mismatches, priority mismatches, cross-plant allocations, or cross-unit allocations.
