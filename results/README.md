# Evaluation Explainer

## Evaluation scope

`phase7_stratified_100` contains the retained formal LLM evaluation. It uses a fixed-seed stratified sample of four order-level fact packages from each of 25 synthetic workbooks, producing 100 evaluated orders from a population of 2,673 eligible orders.

## Main artifacts

- `evaluation_manifest.json` and `.csv`: selected workbook and order records, sampling strata, source fingerprints, and execution state
- `llm_calls.jsonl`: publication-safe structured inputs, model outputs, token usage, latency, and cost
- `preflight_audit.json`: 100/100 payload rebuild and cross-order leakage checks
- `recommendation_ratings.csv`: action-level evidence ratings
- `ai_assisted_review.json`: recorded review method and reviewer identity
- `evaluation_summary.json` and `.csv`: aggregate metrics
- `phase7_evaluation_report.md`: human-readable report

The companion review workbook is stored at `outputs/phase7_stratified_100/phase7_human_evaluation_100.xlsx`.

## Current result

All 100 planned calls completed successfully. The responses contained 162 actions, and the recorded AI-assisted evidence review rated all 162 as Supported. Exact API cost was `$0.35055240` and average response time was 10.089 seconds.

## Interpretation limits

The review was AI-assisted rather than independent human-only review. The 0% unsupported rate checks whether generated explanations and evidence support deterministic canonical actions. It is not an overall model-accuracy rate, a planner usability study, an evaluation of every eligible order, or a guarantee of real-world performance.

## Reproduction without paid calls

The following commands rebuild the retained audit and reports without making another API call:

```powershell
python scripts/audit_phase7_preflight.py results/phase7_stratified_100/evaluation_manifest.json --output results/phase7_stratified_100/preflight_audit.json --compatibility-mode
python evaluate_phase7.py status
python evaluate_phase7.py ratings
python evaluate_phase7.py report
```

Do not run `python evaluate_phase7.py run` unless a new live evaluation and its API cost are intentional. See [LLM Evaluation](../docs/llm_evaluation.md) and [LLM Safety](../docs/llm_safety.md) for the full method and controls.
