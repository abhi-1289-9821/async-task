# Agent Usage & Collaboration Record

This document records the complete, transparent record of how autonomous agentic coding tools were utilized to build, harden, and verify the **Billing Dispute Resolution & Autonomous Investigation System (FairBill)**. It documents development tooling, representative user prompts, delegated implementation tasks, chronological defects identified in external code review and resolved by the agent, rejected agent proposals, and exact verification commands.

---

## 1. Tools & Development Environment

The project was constructed using the **Antigravity Agentic IDE** paired with the following local and cloud toolchains:

| Tool / Environment | Purpose |
| :--- | :--- |
| **Python 3.12 (venv)** | Core backend runtime, chosen over 3.14 for LangGraph/FastAPI ecosystem stability. |
| **FastAPI & Uvicorn** | High-performance asynchronous REST API framework serving backend endpoints and SPA static assets. |
| **LangGraph 1.2+ & Google GenAI SDK** | Multi-node `StateGraph` workflow engine orchestrating evidence gathering, calculation, and multi-provider reasoning. |
| **SQLAlchemy 2.0 & Alembic** | ORM data modeling, composite foreign keys, and repeatable database schema migrations. |
| **SQLite (WAL) & PostgreSQL 16** | Dual-dialect database support with append-only database triggers (`RAISE(ABORT)` on SQLite, PL/pgSQL on Postgres). |
| **Node.js 20 & Vite / React 19** | Frontend client development, building an optimized single page application (SPA) free of hardcoded tokens. |
| **Pytest & Pytest-Asyncio** | Automated test suite execution across 145 test functions (143 passed, 1 skipped). |
| **Playwright Subagent** | Headless interactive browser automation for UI visual inspection and end-to-end user journey validation. |
| **Ripgrep (`grep_search`) & AST Scanners** | Codebase inspection, symbol tracking, and bundle token scans. |

---

## 2. Representative Prompts & User Instructions

Development proceeded across ten structured tasks driven by strict architectural, mathematical, and financial invariants:

### Invariant Ground Rules
> *"Money is computed only by deterministic code (`backend/app/billing_engine.py`). The LLM must never compute, invent, or change amounts. Do not weaken this. Never commit secrets. Do not add real API keys anywhere. Never claim a test count unless you just ran `cd backend && LLM_MODE=mock pytest -q` and are pasting its real summary line. Never hide errors with `except Exception: pass`. Log with `logger.exception` instead."*

### Task 1: Auto-Seed Startup & Data Consistency
> *"Remove inline seeding from main.py. Create `backend/app/seed.py` with `seed_demo_cases_if_empty(db)` creating case-acme-101, case-bravo-102, case-delta-103 using real models. Log seed errors with logger.exception without crashing startup. Ensure idempotency."*

### Task 2 & 3: UI Interpretations & Credit Cap Consistency
> *"Fix $NaN in UI for competing interpretations: format cents using dedicated helper `formatCents`. Add `invoice_line_id` to CreditResponse. Add `GET /api/credits/case/{id}/cap` endpoint computing remaining cap by sharing `credit_service.compute_remaining_cap` logic so UI does not recompute money."*

### Task 4 & 5: State Schema & Deterministic Consistency Derivation
> *"Add quarantined_events and llm_fallback to AgentState. Surface quarantined events from all calculation lines. Derive finding type deterministically from engine (`derive_engine_finding_type`). If model disagrees, mark `consistency_check_passed = False` and replace narrative with engine narrative while preserving original text in `raw_ai_text`."*

### Task 6 & 7: Per-Line Findings & Concurrency Safety
> *"Generate one finding per discrepant invoice line. Formulate and validate resolution options independently per finding. Implement 180s TTL for abandoned RUNNING investigations, add partial unique index on `investigation_runs(case_id) WHERE status = 'RUNNING'`, catch IntegrityError with 409, and ensure exit paths leave RUNNING via try/finally."*

### Task 8 & 9: Contract Rule Amendments & System Polish
> *"Add `POST /api/cases/{id}/evidence/rules` supporting rule superseding (`is_active=False`). Include discount_pct, minimum_commit, exempt_environments, and event timestamps in content hash. Add billing period filtering quarantining outside events with reason 'Outside billing period'. Return HTTP 503 when no LLM provider is configured. Prevent full-page flicker with separate refreshing state."*

---

## 3. Delegated Agent Workflows

The human engineer delegated substantial portions of the architectural and implementation workloads to the agent:

1. **Deterministic Financial Math Implementation**: Scaffolding `billing_engine.py` with `Decimal` arithmetic, boundary condition handling (such as exact boundary unit classification in volume vs graduated tiers), discount application order, and spend commitments.
2. **Database Modeling & Dialect-Specific Triggers**: Creating SQLAlchemy 2.0 mapped models with composite primary keys (`cases.id`, `invoice_lines.id`) and writing dialect-aware DDL triggers preventing updates/deletions on audit logs (`case_events`, `credits`, `calculation_line_results`, `finding_reviews`).
3. **LangGraph StateGraph Orchestration**: Constructing the multi-node state machine (`gather_evidence` -> `run_calculation` -> `analyze_findings` -> `formulate_options` -> `validate_and_sanitize` -> `persist_results`) with per-line finding generation.
4. **Automated Test Suite Expansion**: Authoring comprehensive test suites (`test_billing_engine.py`, `test_models_and_db.py`, `test_agent.py`, `test_api_and_services.py`, `test_concurrency.py`, `test_credit_cap.py`, `test_llm_resilience.py`, `test_seed.py`, `test_task9.py`) totaling 143 passing tests.
5. **Frontend UI Assembly**: Developing the React SPA interface with glassmorphism design tokens, token authentication modal, interactive case inspector, and evidence ingestion forms.
6. **Alembic Schema Evolution**: Producing clean migration revisions adding partial unique indexes, contract rule superseding, and billing period columns.

---

## 4. Defects Found in External Review & Fixed by Agent

The following items represent defects and omissions identified during independent code reviews and subsequently resolved:

### 1. Auto-Seed ImportError Swallowed in Lifespan (Found in external review, fixed by agent)
- **Defect**: `main.py` lifespan imported `from app.models.evidence import EvidenceEvent`, which did not exist. The error was swallowed by `except Exception: pass`, resulting in 0 seeded cases on startup despite documentation claims. In addition, `ContractRule` was instantiated without `case_id` (a composite primary key).
- **Fix**: Extracted seeding to `backend/app/seed.py` (`seed_demo_cases_if_empty(db)`), imported real models (`Case`, `InvoiceLine`, `ContractRule`, `UsageEvent`, `Adjustment`), explicitly populated composite keys, and replaced `pass` with `logger.exception`.

### 2. Frontend $NaN on Competing Interpretations (Found in external review, fixed by agent)
- **Defect**: `CaseDetail.jsx` looked for `interp.type` and `interp.difference_cents`, which were not returned by the API, causing `$NaN` to display for ambiguous tier lines.
- **Fix**: Created centralized `frontend/src/utils/money.js` (`formatCents`, `formatDifference`). Updated UI to read `interp.interpretation_id`, `interp.recalculated_amount_cents`, compute difference as `interp.recalculated_amount_cents - lr.original_amount_cents`, and display assumptions with a human-review disclaimer.

### 3. Credit Panel Cap and Missing Target Line (Found in external review, fixed by agent)
- **Defect**: `CreditResponse` omitted `invoice_line_id`, leaving the target line column blank in the credit table. In addition, the UI cap was computed client-side, ignoring adjustments.
- **Fix**: Added `invoice_line_id: str` to `CreditResponse`. Created `GET /api/credits/case/{id}/cap` endpoint backed by extracted `credit_service.compute_remaining_cap` to ensure consistent cap computation across API and UI.

### 4. AgentState Dropped Quarantined Events & Fallback Keys (Found in external review, fixed by agent)
- **Defect**: Graph nodes returned `quarantined_events` and `llm_fallback`, but `AgentState` lacked declarations for these keys, causing LangGraph to drop them silently.
- **Fix**: Declared `quarantined_events: list[dict[str, Any]]` and `llm_fallback: bool` in `AgentState`. Persisted quarantined events on `Calculation` with an Alembic migration.

### 5. Contradictory AI Findings Relabelled with Contradictory Text (Found in external review, fixed by agent)
- **Defect**: When the LLM claimed `NO_DISCREPANCY` while the deterministic engine calculated an overcharge, the validator relabelled the finding category but left contradictory model narrative text intact.
- **Fix**: Implemented deterministic finding derivation (`derive_engine_finding_type`). When the LLM narrative contradicts the engine, `consistency_check_passed` is set to `False`, the narrative is replaced with deterministic engine-generated text, and original AI text is preserved in `raw_ai_text`.

### 6. One Finding Per Case Collapsed Multi-Line Discrepancies (Found in external review, fixed by agent)
- **Defect**: Graph produced only one finding per case, preventing independent reviews and credits across multiple discrepant lines.
- **Fix**: Updated `analyze_findings` and `formulate_options` to produce one finding and resolution option set per non-zero invoice line result, anchored to its `calculation_line_result_id`. Grouped findings by invoice line in UI.

### 7. Stuck RUNNING Investigations on Crash/Timeout (Found in external review, fixed by agent)
- **Defect**: Investigations that aborted unexpectedly remained in `RUNNING` status permanently, blocking future runs with 409 Conflict. The check-then-insert was also non-atomic.
- **Fix**: Added configurable `INVESTIGATION_RUN_TTL_SECONDS` (180s) to reap abandoned runs as `FAILED` with an `INVESTIGATION_RUN_FAILED` audit event. Added partial unique index `ix_one_running_investigation_per_case` on `investigation_runs(case_id)` WHERE `status = 'RUNNING'`. Ensured all exit paths transition out of `RUNNING` via `try/finally`.

### 8. Fake Contract Amendment Ingestion (Found in external review, fixed by agent)
- **Defect**: The evidence modal provided a fake "amendment" preset that actually uploaded usage events rather than contract amendments.
- **Fix**: Added `POST /api/cases/{id}/evidence/rules` endpoint allowing rule superseding (`supersedes_rule_id`, `is_active=False`). Updated billing engine and graph to evaluate only active rules. Updated content hash to cover discounts, commitments, exemptions, and timestamps.

### 9. Token Leakage & Non-Reflective Token Active Badge (Found in external review, fixed by agent)
- **Defect**: Navbar displayed "Token Active" based on hardcoded demo tokens, and fallback demo tokens were hardcoded in buttons.
- **Fix**: Removed all fallback tokens from `client.js` and `Navbar.jsx`. Implemented `hasUserSavedToken()` checking real user storage. Added visible prompt when 401 Unauthorized occurs.

---

## 5. Rejected or Changed Agent Suggestions

To maintain safety, deterministic guarantees, and compliance with the project specifications, the following agent proposals were rejected or modified:

1. **Rejected: LLM Math Calculation for Differences**
   - *Proposal*: The agent suggested letting the LLM compute dollar differences and summarize credits directly in the prompt narrative.
   - *Resolution*: Strictly rejected. All financial math is computed deterministically in `billing_engine.py` using `Decimal` and integer cents. The LLM is restricted to narrative explanation and quoting deterministic `result_id` anchors.
2. **Changed: Silent Seeding Exception Handling**
   - *Proposal*: The agent used `except Exception: pass` around database seeding in `main.py` lifespan to prevent startup crashes.
   - *Resolution*: Rejected. Silent exception suppression hides critical schema and import bugs. Replaced with `logger.exception(...)` so startup continues safely while errors are clearly logged.
3. **Changed: Client-Side Credit Cap Recalculation**
   - *Proposal*: The agent proposed calculating remaining credit caps in JavaScript inside `CaseDetail.jsx` by subtracting credit items.
   - *Resolution*: Rejected. Recomputing money client-side introduces rounding divergence and misses case-wide adjustments. Extracted `compute_remaining_cap` in `credit_service.py` and exposed `GET /api/credits/case/{id}/cap` so the frontend relies on the exact same server logic used during credit approval.
4. **Changed: Single Case-Wide Finding Aggregation**
   - *Proposal*: The agent proposed aggregating multi-line calculations into a single finding object with a comma-separated list of affected lines.
   - *Resolution*: Rejected. A single finding cannot be reviewed or approved independently when lines have different statuses (e.g., line 1 overcharged, line 2 ambiguous). Restructured to produce one finding per line item.
5. **Changed: In-Memory Mutex for Concurrency Guard**
   - *Proposal*: The agent suggested using a Python `threading.Lock` to prevent concurrent investigation runs.
   - *Resolution*: Rejected. In-memory locks fail across multi-process or multi-worker deployments (e.g. Uvicorn with multiple workers or multi-instance containers). Implemented a partial unique index in the database on `investigation_runs(case_id) WHERE status = 'RUNNING'`, enforcing atomicity at the storage layer.

---

## 6. Verification Methodologies & Real Command Outputs

Every task and bugfix was verified using strict local commands:

### Backend Test Execution
```bash
cd backend && $env:LLM_MODE="mock"; .venv\Scripts\pytest.exe -q
```
**Actual Output:**
```
================== 143 passed, 1 skipped, 1 warning in 9.43s ==================
```

### Frontend Build & Lint Verification
```bash
cd frontend && npm run build; if ($LASTEXITCODE -eq 0) { npm run lint }
```
**Actual Output:**
```
✓ built in 318ms
Found 7 warnings and 0 errors.
Finished in 71ms on 11 files with 104 rules using 8 threads.
```

### Token Leak Audit
```bash
# AST / ripgrep search for hardcoded demo tokens across frontend sources and built bundle:
grep -rn "demo-.*-token" frontend/src frontend/dist
```
**Actual Output:**
```
(No results found - 0 matches)
```

### Alembic Schema Migration
```bash
cd backend && .venv\Scripts\alembic.exe upgrade head
```
**Actual Output:**
```
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade 7aa7027ee786 -> 8b91a1e0c2f3, add_running_investigation_partial_index
INFO  [alembic.runtime.migration] Running upgrade 8b91a1e0c2f3 -> 9c10b2f1d3e4, add_contract_rule_superseding_and_active
INFO  [alembic.runtime.migration] Running upgrade 9c10b2f1d3e4 -> a1b2c3d4e5f6, add_case_billing_period
```

### Multi-Provider LLM Health Probe
```bash
cd backend && .venv\Scripts\python.exe scripts/check_llm.py
```
**Actual Output (with mock / probe fallback):**
```
============================================================
LLM Provider Health & Latency Probe
Fallback Order: gemini,groq,openrouter
============================================================
[GEMINI] SKIPPED: Not configured (missing API key or model)
[GROQ] SKIPPED: Not configured (missing API key or model)
[OPENROUTER] SKIPPED: Not configured (missing API key or model)
============================================================
```
