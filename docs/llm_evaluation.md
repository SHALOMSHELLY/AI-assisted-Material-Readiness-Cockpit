# LLM Evaluation

## Scope

The current formal evaluation uses a fixed-seed stratified sample of four order-level fact packages from each of the 25 synthetic workbooks, for 100 unique selections. This is broader than the earlier one-order-per-workbook run, but it is still a sample rather than an all-order correctness claim. The Streamlit AI selector excludes Pending Scheduling orders because they have no verified production requirement. However, the retained formal evaluation includes 19 bounded unscheduled-order payloads to test scheduling-exception explanations and safeguards.

The evaluator uses the same bounded order-level payload builder as the Streamlit UI. A payload contains at most 15 affected-material rows and 10 relevant PO rows, with explicit truncation counters. The ledger records the structured input, raw and parsed output, local schema/evidence validation, tokens, latency, model, prompt/schema versions, and exact or estimated cost.

## Preflight integrity audit

Before live calls, `scripts/audit_phase7_preflight.py` rebuilds all 100 payloads from the recorded workbook, analysis date, engine version, and selected order. The audit requires:

- an exact payload match for every selection;
- 100 unique workbook/order selections;
- no order, production-order, material, PO, or exception evidence from another selected order;
- retention of the original paid-call source fingerprint and the current public-code fingerprint;
- exact payload equivalence when compatibility mode is used for UI, authentication, or report-only changes.

The public-release preflight integrity audit passes 100/100 exact rebuilds with no cross-order leakage. It reports the original paid-call source fingerprint separately from the current public-code fingerprint instead of pretending the paid calls were rerun. Its result is stored in `results/phase7_stratified_100/preflight_audit.json`.

## Current real evaluation

- Dataset: 25 deterministic synthetic workbooks
- Evaluated order-level payloads: 100
- Eligible orders in the deterministic population: 2,673
- Eligible exceptions: 6,958
- Model: `openai/gpt-4.1-mini`
- Prompt: `phase6-prompt-v15-python-canonical-actions`
- Schema: `phase6-schema-v10-overdue-schedule-impact`
- Successful calls: 100/100
- Failed calls: 0
- Input tokens: 674,233
- Output tokens: 101,801
- Total tokens: 776,034
- Average latency: 10.089 seconds
- Maximum latency: 23.190 seconds
- Exact API cost: `$0.35055240`
- Separate list-price estimate: `$0.43257480`

The 100 responses contained 162 recommended actions. The AI-assisted evidence review recorded 162 Supported, 0 Partially Supported, 0 Unsupported, and 0 Contradictory actions. The reviewer is identified as `Codex (AI-assisted review)`.

The 0% unsupported rate is not an overall correctness rate. Canonical action selection is deterministic, and the review checks whether the generated narrative and evidence support those actions. It is not an independent human-only review and does not prove every one of the 2,673 eligible orders is correct.

## Reproduction

```powershell
python scripts/audit_phase7_preflight.py results/phase7_stratified_100/evaluation_manifest.json --output results/phase7_stratified_100/preflight_audit.json --compatibility-mode
python evaluate_phase7.py status
python evaluate_phase7.py ratings
python evaluate_phase7.py report
```

These commands make no paid API calls. The separate `run` command is explicit and resumable; do not invoke it merely to rebuild a report.

Current artifacts:

- `results/phase7_stratified_100/evaluation_manifest.json`
- `results/phase7_stratified_100/evaluation_summary.json`
- `results/phase7_stratified_100/llm_calls.jsonl`
- `results/phase7_stratified_100/preflight_audit.json`
- `results/phase7_stratified_100/recommendation_ratings.csv`
- `results/phase7_stratified_100/ai_assisted_review.json`
- `results/phase7_stratified_100/phase7_evaluation_report.md`
- `outputs/phase7_stratified_100/phase7_human_evaluation_100.xlsx`

The public ledger retains evaluation content and metrics but replaces full provider generation IDs with irreversible SHA-256 labels. `scripts/evaluate_llm_mock.py` remains available for a no-cost local schema and evidence safety check. Mock results must never be presented as real model-quality results, and unavailable cost must not be reported as zero.
