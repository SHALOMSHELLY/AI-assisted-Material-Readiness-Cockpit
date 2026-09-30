# AI-Assisted Material Readiness Cockpit

A deterministic supply-chain planning cockpit for the fictional manufacturer **Apex Industrial Controls**. All included ERP-style workbooks are synthetic. The project contains no real company, customer, supplier, or employee records.

Users upload one Excel workbook containing `Orders`, `BOM`, `Inventory`, `Incoming_PO`, and `Production_Orders`. Python validates and calculates BOM demand, usable inventory, incoming-supply allocation, shortages, exceptions, priorities, and responsible business functions. The optional AI Planning Copilot explains one verified order-level fact package and proposes review steps. It cannot recalculate the facts, send messages, create purchase orders, reschedule production, or modify ERP data.

## Requirements

- Python 3.12
- Windows 11 for interactive installation and Streamlit use
- Internet access only when installing packages or explicitly using the AI feature
- An OpenRouter API key only for optional AI generation

The deterministic application and all automated tests run without an API key. GitHub Actions separately checks the automated test suite on Ubuntu; interactive macOS use has not been validated.

## Install

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

`requirements.txt` pins the tested direct dependencies. `requirements-lock.txt` records the complete package set used for final verification.

## Run

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Open the local Streamlit address shown in the terminal. Upload a valid workbook, choose an analysis date, validate, and run deterministic analysis.

## API key setup and handling

### Streamlit interface (recommended)

No `.env` file is needed for normal interactive use. After running the app, open **AI Planning Copilot**, paste an OpenRouter key into the password-style **OpenRouter API Key** field, and click **Generate Advisory Action Plan**. The field is part of the Streamlit interface; the key remains only in the current Streamlit session and is used only when generation is explicitly requested.

### Command-line evaluation (optional, may incur API cost)

The command-line evaluation runner can read the key from a local `.env` file. Use this only when intentionally making live evaluation calls:

```powershell
Copy-Item .env.example .env
```

Then replace the placeholder in `.env` with a valid key. The `.env` file is ignored by Git and must never be committed. Existing retained evaluation reports, status commands, ratings, and report generation do not require another paid call.

### Automated tests

The complete automated test suite does not need a real API key and does not make paid LLM calls. API-related tests inject a fake key and mock the HTTP response.

For both interface and command-line use, the real key:

- is passed only in the OpenRouter Authorization header;
- is not included in the AI payload, exports, cache key, evaluation ledger, or error messages;
- is not required for deterministic analysis.

## Cockpit views

- **Overview**: decision KPIs, exception and priority charts, and top-risk orders.
- **My Orders**: all sales orders in the loaded scope, scheduling status, material readiness, shortages, and relevant supplier evidence.
- **My Materials & Supplier POs**: material/plant readiness, exact allocated PO schedule lines, and receipt-date eligibility.
- **Pending Scheduling**: open sales orders without a valid active linked production order.
- **AI Planning Copilot**: one bounded order-level payload, evidence-bound advisory actions, missing information, limitations, human-review requirement, and `NOT_EXECUTED` status.

“My” means the currently loaded planning scope. The prototype has no authentication, planner ownership, multi-tenancy, or employee assignment.

## Test

```powershell
.\.venv\Scripts\python.exe -m pytest -q -m "" -p no:cacheprovider
```

The complete local suite currently passes 288 tests. It covers workbook validation, BOM demand, inventory and PO allocation, exact PO schedule-line matching, order-status precedence, exceptions, priorities, bounded AI payloads, LLM schema/evidence safety, Streamlit behavior, formal Oracle comparisons, and performance guards. Automated tests never make a paid LLM call.

GitHub Actions runs the same complete automated suite on Ubuntu with Python 3.12. This CI check validates the test suite in a clean Linux environment; it is not a hosted Streamlit deployment or a claim of manual Linux/macOS interface testing.

## Synthetic formal dataset

`data/expanded_scenarios` contains 25 reproducible workbooks:

- Small: 9
- Medium: 8
- Large: 8

The independent Oracle does not import the production shortage, exception, or priority engines.

```powershell
python data/expanded_scenarios/generators/generate_expanded_workbooks.py --overwrite
python scripts/build_scenario_artifacts.py
python scripts/evaluate_oracles.py
```

The deterministic target is 25/25 workbooks with zero missing rows, unexpected rows, quantity mismatches, priority mismatches, cross-plant allocation, or cross-unit allocation.

## Current LLM evaluation artifacts

The retained evaluation uses a fixed-seed stratified sample of four order-level fact packages per workbook:

- 25 synthetic workbooks
- 100 unique evaluated orders
- 100/100 successful calls
- 162 rated actions
- 162 Supported
- 0 Partially Supported
- 0 Unsupported
- 0 Contradictory
- 674,233 input tokens
- 101,801 output tokens
- exact API cost: `$0.35055240`
- list-price estimate: `$0.43257480`

The reviewer is recorded as `Codex (AI-assisted review)`. This is not an independent human-only review and is not an all-order correctness claim.

Public artifacts are under `results/phase7_stratified_100`. The public ledger retains all synthetic inputs, outputs, token counts, latency, and cost, but replaces provider generation IDs with irreversible SHA-256 labels. The review workbook is `outputs/phase7_stratified_100/phase7_human_evaluation_100.xlsx`.

The paid calls retain their original evaluated source fingerprint in the manifest. This public release adds runtime API-key input and presentation-only cleanup without changing the deterministic payload builder, prompt version, or schema version. Compatibility auditing therefore reports the original call fingerprint and the current public-code fingerprint separately while still requiring all 100 payloads to rebuild exactly.

```powershell
python scripts/audit_phase7_preflight.py results/phase7_stratified_100/evaluation_manifest.json --output results/phase7_stratified_100/preflight_audit.json --compatibility-mode
python evaluate_phase7.py status
python evaluate_phase7.py ratings
python evaluate_phase7.py report
```

These commands make no API calls. Do not run `evaluate_phase7.py run` unless you intentionally accept real API cost.

## Repository privacy

The repository is prepared for public upload:

- no `.env` file or virtual environment;
- no raw provider generation IDs;
- no local absolute paths in retained reports;
- no real business data;
- no file near GitHub's 100 MB per-file limit;
- caches, IDE settings, logs, uploads, and temporary test output are ignored.

To rebuild a publication-safe ledger from a private source file:

```powershell
python scripts/sanitize_public_artifacts.py path/to/private_calls.jsonl results/phase7_stratified_100/llm_calls.jsonl
```

Never commit the private source ledger.

## Documentation

- [Demo Guide](docs/demo_guide.md)
- [Data Design](docs/data_design.md)
- [Data Dictionary](docs/data_dictionary.md)
- [Calculation Rules](docs/calculation_rules.md)
- [Validation Rules](docs/validation_rules.md)
- [Exception Rules](docs/exception_rules.md)
- [Priority Rules](docs/priority_rules.md)
- [LLM Safety](docs/llm_safety.md)
- [LLM Evaluation](docs/llm_evaluation.md)
- [Test Report](docs/test_report.md)

## Limits

There is no SAP connection, ERP write-back, email/chat delivery, employee assignment, authentication, database, scheduler, multi-tenancy, automatic purchasing, automatic rescheduling, LangChain/LangGraph, or autonomous agent workflow. Suggested business functions are deterministic routing hints, not employee assignments. Workflow status is session-only and excluded from the LLM fact package. Every AI output is advisory and requires human review.
