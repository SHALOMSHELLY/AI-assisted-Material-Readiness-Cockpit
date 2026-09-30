# Phase 7 LLM Evaluation Report

## Evaluation Objective

**Unsupported Recommendation Rate: 0.00% (0/162).**

This is not an overall correctness rate. The Fully Supported Rate is 100.00%; the Non-Fully-Supported Rate is 0.00%.

Status: **COMPLETE**. Total recommendations: 162; rated: 162; unrated: 0. A report with unrated recommendations is not final.

## Fixed Dataset

The evaluation uses 25 fixed synthetic SAP-style workbooks, not official SAP production exports. Valid workbooks: 25; Data Error workbooks: 0; planned calls: 100.

Evaluation scope: Fixed-seed stratified sample of four order-level fact packages per workbook; not an all-order correctness claim. Eligible orders: 2673; evaluated orders: 100; eligible exceptions: 6958.

## Model and Configuration

- Model: `openai/gpt-4.1-mini`
- Prompt: `phase6-prompt-v15-python-canonical-actions`
- Schema: `phase6-schema-v10-overdue-schedule-impact`
- Analysis date: `2026-09-25`
- Pricing snapshot: `2026-09-24`

## Evaluation Procedure

Validation and deterministic Python analysis run first; Data Errors block LLM calls. Each selected result receives at most one formal generation with no automatic retry. Each recommended action is rated separately, and deterministic flags are review aids only. Review method: AI-assisted review (Codex (AI-assisted review)).

## Recommendation Metrics

- Supported Rate: 100.00% (162/162)
- Partially Supported Rate: 0.00% (0/162)
- Unsupported Recommendation Rate: 0.00% (0/162)
- Contradiction Rate: 0.00% (0/162)
- Non-Fully-Supported Rate: 0.00%
- High-Risk Recommendation Rate: 0.00%

## Cost

- Exact API cost: `$0.35055240` across 100 calls
- Estimated cost: `$0.43257480` across 100 calls
- Exact cost per valid workbook: `$0.01402210`
- Exact cost per planned workbook: `$0.01402210`
- Deterministic Python calculation cost: `$0`

Exact and estimated totals are kept separate.

## Tokens and Latency

- Successful calls: 100
- Failed calls: 0
- Input tokens: 674233
- Output tokens: 101801
- Total tokens: 776034
- Average tokens per call: 7760.34
- Minimum/average/maximum latency: 4.104202599963173 / 10.089177008995321 / 23.190079299965873 seconds

Safe error categories: `{}`.

Data Error workbooks: `None`.

## Limitations

The sample is synthetic and the review is AI-assisted rather than independent human-only review. One generation model and one reviewing system do not represent all models. Provider versions and prices may change, and free text cannot be guaranteed hallucination-free.

The system does not modify SAP, create purchase orders, send messages, or execute recommendations. Every recommendation requires planner review.
