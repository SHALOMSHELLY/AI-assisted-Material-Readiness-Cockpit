# LLM Safety Boundary

## Source of truth and privacy

The deterministic Python engine is the sole source of truth. The LLM receives only the selected order-level fact package shown in the preview, not the API key, raw workbook, or unrelated rows. It does not recalculate business results.

## Enforced output

OpenRouter requests use strict JSON Schema. Top-level, action, and Evidence objects reject extra fields. Action types and missing-information codes use local allowlists. Every action must set `requires_human_approval=true` and `execution_status=NOT_EXECUTED`.

Evidence supplies `field`, `value`, and `unit`. Fields must be allowlisted, values must exactly match the sent Python facts, and quantity units must match `Quantity_Unit`. Python priority and rule ID must also be returned unchanged and validated locally.

The remote schema uses broadly supported constructs such as `type`, `properties`, `required`, `additionalProperties: false`, `enum`, and `anyOf`. Local Python additionally enforces non-empty strings, non-empty Evidence, unique codes, and business-policy checks.

## Failure isolation

Structural validation blocks wrong fields, altered evidence, wrong units, unknown codes, and executed status. It cannot prove that every free-text statement is semantically correct, so narrative text remains advisory.

Missing keys, timeouts, HTTP errors, invalid JSON, unsupported strict Structured Outputs, or local validation failures affect only the AI area. Deterministic Python results and downloads remain intact. The client does not downgrade to loose JSON mode.

## Calls, cache, and cost

Calls occur only after a separate user action, time out after 45 seconds, have no automatic retries, and request at most 6,000 output tokens. Responses that reach the token limit are rejected as incomplete. Successful results are cached only in the current Streamlit session. The cache key includes workbook SHA-256, date, selected result row, model, prompt version, and schema version.

Usage metadata records input/output/total tokens, response time, generation ID, and optional provider-reported cost. Invalid or missing metadata does not change the generated explanation or Python result. Exact provider cost and list-price estimated cost are always labeled separately; unavailable cost is shown as N/A, never zero.

## Action support

Evidence matching proves correct citation, not sufficient action support by itself. For example, an expedite action requires a positive shortage and positive late or overdue incoming quantity. Eligible on-time supply is already included in available supply and does not alone support expediting.

Local policy also rejects no-action advice with a positive shortage, procurement escalation with zero shortage, and rescheduling, cross-order allocation, or alternative-material advice unsupported by the selected order-level facts.

## Evaluation ledger

The formal evaluation uses fixed synthetic workbooks only. Manifest and rating operations do not read the API key. Live calls require explicit confirmation, and every completed attempt is appended and flushed immediately to UTF-8 JSONL.

The ledger stores no API key, Authorization header, `.env`, or Excel binary. It does store the selected synthetic fact package, model output, tokens, latency, and cost. The public ledger replaces provider generation IDs with irreversible SHA-256 labels. Successful selections are not repeated during resume; failed retries must be explicit and may create additional cost.

The current 100-call run was reviewed by `Codex (AI-assisted review)`. That review checks evidence support but is not an independent human-only review. Every recommendation remains advisory and requires planner approval.
