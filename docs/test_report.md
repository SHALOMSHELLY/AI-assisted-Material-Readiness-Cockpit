# Test Report

## Current result

The complete suite passes **288/288 tests** after the frontend/backend consistency fixes, session-only API-key UI, public-artifact sanitization, and unused-code cleanup. A clean Python 3.12 environment installed directly from `requirements.txt` completed the full run in 111.55 seconds on Windows.

The deterministic Oracle evaluation passes all 25 synthetic workbooks with zero missing rows, unexpected rows, quantity mismatches, priority mismatches, cross-plant allocations, or cross-unit allocations.

The current real LLM evaluation is also complete: 100/100 calls succeeded, 162/162 actions were rated Supported by the recorded AI-assisted review, and exact API cost was `$0.35055240`. See `docs/llm_evaluation.md` for scope and limitations.

## Commands

```powershell
python scripts/build_scenario_artifacts.py
python scripts/evaluate_oracles.py
python scripts/evaluate_llm_mock.py
python -m pytest -q
python -m pytest -q -m formal_oracle
python -m pytest -q -m performance
python -m pytest -q -m llm_mock
python -m pytest -q -m ""
```

The first three scripts generate their own result files when run. Those generated files are not part of the retained current-result set unless explicitly preserved. The authoritative retained LLM artifacts are under `results/phase7_stratified_100`.

The tests cover workbook validation, BOM demand, inventory and PO allocation, exact PO schedule-line matching, order status precedence, deterministic exceptions and priorities, bounded order payloads, session-only API-key forwarding, LLM schema/evidence safety, Streamlit state behavior, formal Oracle comparisons, and performance guards.
