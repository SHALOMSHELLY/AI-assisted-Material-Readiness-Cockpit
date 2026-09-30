# Performance Report

Measured on 2026-09-27 using Python 3.12.10 on Windows 11 (`AMD64`, local filesystem). Each scenario was run three times with `time.perf_counter()`; the table reports medians. Excel read, validation, deterministic shortage calculation, exception generation, and both summaries are included. Baseline shortage timing contained its then-current internal second validation; optimized timing reuses the already completed validation report.

| Workbook | Before total (s) | After total (s) | Speedup | Excel read (s) | Validation (s) | Shortage engine (s) | Exceptions (s) | Summaries (s) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| M08 | 6.536 | 0.671 | 9.75x | 0.066 | 0.365 | 0.208 | 0.011 | 0.021 |
| L01 | 23.210 | 1.652 | 14.05x | 0.122 | 0.930 | 0.530 | 0.020 | 0.035 |
| L04 | 30.731 | 1.866 | 16.47x | 0.151 | 1.046 | 0.631 | 0.017 | 0.019 |
| L08 | 44.645 | 2.269 | 19.68x | 0.173 | 1.303 | 0.715 | 0.026 | 0.044 |

The baseline profile showed repeated whole-table BOM, inventory, and PO filtering inside production-order loops, plus validation running twice. The optimized implementation pre-converts BOM dates, builds product/plant and material/plant indexes, creates stable `(Material_ID, Plant, Quantity_Unit)` receipt pools, and advances per-pool cursors. It preserves deterministic ordering and never shares supply across keys.

The formal 25-workbook Oracle run took 21.795 seconds in total. The largest single Large runtime was 2.356 seconds (L07). The timing table above is the retained historical record; the temporary machine-readable profiling files were removed during result cleanup.

Commands:

```powershell
python -m pytest -q
python -m pytest -q -m formal_oracle
python -m pytest -q -m performance
python -m pytest -q -m llm_mock
python -m pytest -q -m ""
python scripts/evaluate_oracles.py
python scripts/evaluate_llm_payloads.py
```
