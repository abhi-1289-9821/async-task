# Agent Log — Billing Dispute Investigation and Resolution Agent

> Append-only. Every mistake, correction, rejection, and fix is recorded here.
> This feeds directly into AGENT_USAGE.md at the end of Phase 5.

---

## Format

Each entry: Phase, timestamp, category, event, fix, status.

---

## Phase 0

### [Phase 0] [2026-10-13 11:49] — Workspace Inspection
- **Event**: Workspace d:\agg was empty. No existing code to preserve.
- **Fix / Outcome**: Fresh project start confirmed. No conflicts.
- **Status**: resolved

### [Phase 0] [2026-10-13 11:50] — Python Version Risk
- **Event**: Python 3.14.0 is installed. LangGraph 1.2.15 and FastAPI have not been widely tested against 3.14. Real risk of compatibility issues.
- **Fix / Outcome**: Noted as Risk #1. Will install packages and verify imports in Phase 1 before writing implementation code.
- **Status**: open — to verify in Phase 1

### [Phase 0] [2026-10-13 11:50] — GEMINI_API_KEY Not Set
- **Event**: GEMINI_API_KEY and GEMINI_MODEL environment variables are both empty.
- **Fix / Outcome**: Will not block Phases 1-2. User must supply key before Phase 3.
- **Status**: open — user must supply GEMINI_API_KEY before Phase 3

### [Phase 0] [2026-10-13 11:50] — google-genai vs google-generativeai
- **Event**: google-generativeai not installed. google-genai 2.30.0 is the new official SDK. Must verify actual API surface from the installed SDK, not from memory.
- **Fix / Outcome**: Will use google-genai (google.genai import). Will inspect real API in Phase 3.
- **Status**: resolved

### [Phase 0] [2026-10-13 11:50] — npm global directory missing
- **Event**: C:\Users\abhin\AppData\Roaming\npm did not exist, causing npm list -g to fail.
- **Fix / Outcome**: Created the directory. npm now works. Will install Vite in Phase 4.
- **Status**: resolved

### [Phase 0→1 Transition] [2026-10-13 11:58] — User Corrections Applied
- **Event**: User provided 10 corrections to the Phase 0 proposal before approving.
- **Corrections**:
  1. Use Python 3.12 (not 3.14) via venv; pin all versions.
  2. Never assume gemini-1.5-* model name; keep GEMINI_MODEL as pure config.
  3. Add POST /api/findings/{id}/review endpoint; store edit separately; credit requires accepted non-stale finding.
  4. Credit locking: SELECT FOR UPDATE (Postgres) / BEGIN IMMEDIATE (SQLite); add Postgres concurrency test.
  5. State machine: new evidence bumps version+stale in ANY status; REOPENED only from RESOLVED; add REOPENED->AWAITING_INFO; invalid=409 (was 422).
  6. Append-only on case_events enforced by DB trigger; PRAGMA foreign_keys=ON for SQLite.
  7. Scenario 3 = cumulative cap + 409 repeat; Scenario 6 = structural injection test, no audit claim.
  8. Agent: 2 LLM calls (findings+questions+summary / options); gather_evidence abort = BLOCKED status, not a finding.
  9. Auth: Authorization: Bearer <token>; not X-Demo-Role header.
  10. Re-estimate phases tighter; Render/Neon health-check deploy at end of Phase 2.
- **Business rule answers**: A=exempt_environments per rule no default; B=skip tax; C=one discount per line, two=UNRESOLVED, ROUND_HALF_UP at boundary; D=tiers->discount->min_commit; E=inclusive up_to, boundary=that tier; F=approved with stronger locking.
- **Fix / Outcome**: All corrections incorporated. Phase 1 started.
- **Status**: resolved

## Phase 1

### [Phase 1] [2026-10-13 12:00] — langchain-core version conflict
- **Event**: requirements.txt pinned langchain-core==0.3.25 but langgraph 1.2.15 requires >=1.4.7. pip install failed.
- **Fix**: Updated to langchain-core==1.6.10 (latest compatible). Noted conflict before any code was written.
- **Status**: resolved

### [Phase 1] [2026-10-13 12:00] — pydantic version conflict
- **Event**: requirements.txt pinned pydantic==2.10.3 but google-genai 2.30.0 requires >=2.12.5. pip install failed.
- **Fix**: Changed pydantic to >=2.12.5,<3.0.0; resolved version is pydantic 2.14.1.
- **Status**: resolved

### [Phase 1] [2026-10-13 12:06] — Incorrect ROUND_HALF_UP negative test assertion
- **Event**: test_rounds_half_up_negative asserted _round_cents(Decimal('-0.5')) == 0. Python's ROUND_HALF_UP rounds -0.5 to -1 (away from zero), not 0. Test FAILED.
- **Fix**: Corrected assertion to -1 and updated comment to explain the actual semantics. Honesty rule: did not hide this failure.
- **Status**: resolved

### [Phase 1] [2026-10-13 12:30] — SQLite RAISE(ABORT) raises IntegrityError, not OperationalError
- **Event**: Trigger tests initially caught `OperationalError`. SQLite DB-API translates `RAISE(ABORT)` to `sqlite3.IntegrityError` (wrapped by SQLAlchemy as `sqlalchemy.exc.IntegrityError`).
- **Fix**: Updated test assertions to catch `IntegrityError` with the exact trigger abort message. All 60 unit tests pass.
- **Status**: resolved

---

## Phase 2

### [Phase 2] [2026-10-13 13:53] — EvidenceVersion primary key type mismatch
- **Event**: `transition_service.py` attempted to insert string `f"ev_{case_id}_v{version}"` into `EvidenceVersion.id`, which is an autoincrement `Integer` primary key. SQLite raised `IntegrityError: datatype mismatch`.
- **Fix**: Removed manual string `id` assignment so SQLAlchemy and SQLite autoincrement the integer primary key cleanly.
- **Status**: resolved

### [Phase 2] [2026-10-13 13:54] — TierBand and UsageEvent signature mismatches
- **Event**: `calculation_service.py` referenced `engine.PricingTier` (actual name is `engine.TierBand`) and passed `timestamp` to `engine.UsageEvent` (which does not take a timestamp).
- **Fix**: Updated instantiation to `engine.TierBand(price_per_unit_cents=..., up_to=...)` and omitted timestamp from the pure calculation dataclass.
- **Status**: resolved

### [Phase 2] [2026-10-13 13:56] — Concurrency stress test verification
- **Event**: Tested 10 parallel threads simultaneously executing `approve_credit` against the same overcharge line.
- **Outcome**: Verified that exactly 1 thread succeeded with 201 Created, while the competing 9 threads were rejected via cap exhaustion or 409 idempotency key collision. Total credited amount in database strictly equaled the eligible overcharge (zero double-crediting).
- **Status**: resolved

---

## Phase 3

### [Phase 3] [2026-10-13 14:18] — Gemini SDK & model discovery
- **Event**: Live call to `gemini-2.5-flash` returned 404 from Google API ("model is no longer available to new users, update code to gemini-3.8-flash"). High demand returned 503 UNAVAILABLE on alternative preview endpoints.
- **Architecture Validation**: Implemented dual-mode LLM layer: `LLM_MODE=mock` for deterministic offline testing and CI/CD without network flakiness; `LLM_MODE=real` with bounded retries (max 2) and graceful fallback. In production, LLM transient failures yield `PARTIAL` status while preserving the deterministic calculation results.
- **Status**: resolved

### [Phase 3] [2026-10-13 14:21] — LangGraph StateGraph & prompt injection defense
- **Event**: Implemented `InvestigationWorkflow` with nodes: `gather_evidence`, `run_calculation`, `analyze_findings`, `formulate_options`, `validate_and_sanitize`, `persist_results`.
- **Security Invariant**: Isolated untrusted customer dispute statements inside `<untrusted_customer_dispute>` delimiters. System instructions and state machine enforce that user prompts can never override system instructions or fabricate credit amounts.
- **Deterministic Gates**: Missing invoice lines or contract rules abort directly to `RunStatus.BLOCKED` before generating findings. Credit options are strictly anchored to `calculation_line_result_id` from the deterministic engine.
- **Status**: resolved

### [Phase 3] [2026-10-13 14:26] — Citation and consistency validation
- **Event**: Implemented validators in `app.agent.validator`: `validate_citations` catches hallucinated or cross-case citation IDs; `validate_consistency` catches mathematical contradictions between finding claims and calculation results; `sanitize_resolution_options` rejects credit recommendations on non-overcharged lines.
- **Test Suite**: Added 9 tests in `tests/test_agent.py` covering evidence gates, overcharge discrepancy, contract ambiguity, clean calculation, prompt injection safety, validators, and full pipeline (investigation -> human accept review -> credit approval).
- **Outcome**: All 84 tests pass (1 skipped for PostgreSQL in CI).
- **Status**: resolved

---

## Phase 4

### [Phase 4] [2026-10-13 14:50] — React + Vite frontend workspace
- **Event**: Built full-stack React + Vite single page application with glassmorphism dark theme, custom vanilla CSS design tokens, and Lucide icons.
- **Components Built**:
  - `Navbar`: Header with live API connection probe and interactive `REVIEWER` / `VIEWER` Bearer token identity switcher.
  - `CaseList`: Overview with financial exposure stats, status filters (`OPEN`, `AWAITING_INFO`, `RESOLVED`, `REOPENED`), search input, and dispute table.
  - `CreateCaseModal`: Case creation form with 1-click test scenario presets (Tier overcharge, contract ambiguity, clean match, prompt injection attack).
  - `EvidenceModal`: Ingests usage telemetry, demonstrably bumping evidence versions, marking findings stale, and reopening resolved cases.
  - `CaseDetail`: Multi-tab inspection suite containing Deterministic Calculation runner, LangGraph AI investigation panel, human review modal (`ACCEPT`, `EDIT`, `REJECT`), concurrency-safe credit locking approval, and append-only audit timeline.
- **Outcome**: Built production client bundle in 1.35s with 0 errors via `npm run build`.
- **Status**: resolved

---

## Hardening & Deployment Fixes

### [Phase 4+] [2026-10-13 16:05] — Security hardening, wrong-line bug fix & full-stack mount
- **Wrong-Line Credit Guard**: Fixed vulnerability where credit could be approved against a different invoice line item than the calculation result. Added invariant check `line_result.line_id == invoice_line_id` in `credit_service.py` with regression test in `tests/test_api_and_services.py`.
- **Dependency Pin Resolution**: Replaced brittle conflicting pins in `backend/requirements.txt` (`langgraph==1.2.15` vs `langchain-core==0.3.25`) with compatible semantic ranges (`langgraph>=1.2.0,<2.0.0` and `langchain-core>=1.4.7,<2.0.0`), verified via `pip install --dry-run`.
- **Transaction Exception Handling**: Replaced generic `except (OperationalError, Exception): pass` on SQLite `BEGIN IMMEDIATE;` with specific check for `"cannot start a transaction within a transaction"`, preventing silent masking of real database lock errors.
- **Production Startup Security**: Added Pydantic `@model_validator` in `config.py` that halts application startup with a fatal `ValueError` if `ENVIRONMENT=production` runs with default guessable demo tokens.
- **Full-Stack SPA Serving**: Configured `main.py` to automatically detect and serve `frontend/dist` on `/assets` and SPA index routing, enabling unified single-service deployments on Render.
- **Postgres Concurrency Verification Status**: Concurrency lock assertion helper is fully implemented and tested with 10 threads on SQLite. For PostgreSQL (`SELECT FOR UPDATE`), the test function `test_postgres_concurrency_locking` is configured to run against `POSTGRES_TEST_URL` and is conditionally skipped in local environments when no live PostgreSQL URL is configured.
- **Outcome**: 86 tests pass (1 skipped for live Postgres). Clean production build and zero dependency conflicts.
- **Status**: resolved (SQLite concurrency verified; PostgreSQL test stub ready for live Neon connection)

---

## Phase 5: Comprehensive Security, Financial Integrity & Hardening Audit

### [Phase 5] [2026-10-13 16:30] — P0 Financial Math, Security & Crash Fixes
- **SPA Path Traversal Defense**: Enforced `os.path.realpath` containment check in `main.py` SPA catch-all route, preventing `/../../backend/...` directory traversal attacks.
- **Credit Approval Gates for Ambiguous Findings**: Enforced `finding.finding_type == CONFIRMED_CALCULATION_DISCREPANCY` and `line_result.finding_type == CONFIRMED_CALCULATION_DISCREPANCY` in `credit_service.py`. Enforced `difference_cents = 0` on ambiguous lines in `billing_engine.py`.
- **Review Ordering Invariant (ACCEPT-then-REJECT)**: Updated `credit_service.py` to evaluate the latest human review on the finding instead of any historical review, preventing credits from being approved on findings subsequently rejected.
- **Investigation Crash on Prior Adjustments**: Fixed `graph.py` crash by replacing non-existent `a.reason_code` with `a.description` and `a.invoice_line_id`.
- **Deterministic Engine Unresolvable Lines**: Fixed total calculation discrepancy math in `billing_engine.py` by summing individual line item differences (`total_difference = sum(r.difference_cents ...)` and `total_recalculated = total_original + total_difference`), eliminating phantom full refunds on unresolvable lines.
- **Silent Under-Billing Prevention**: Added uncovered usage detection in volume and graduated pricing when usage exceeds the highest bounded tier without an unbounded bracket, returning `INSUFFICIENT_DATA`. Replaced untyped tier dictionaries with typed `TierBandSchema` enforcing ascending order and non-negative rates.
- **Ambiguity Branch Discount & Commit Application**: In `billing_engine.py`, both concrete tier interpretations now evaluate line-level discounts and minimum spend commitments before presenting comparison values.
- **Dialect-Aware Append-Only Triggers**: Added PostgreSQL PL/pgSQL function `block_append_only_modification()` alongside SQLite `RAISE(ABORT)` triggers in `database.py`, preventing startup DDL failures on PostgreSQL while enforcing immutability across `case_events`, `calculation_line_results`, `credits`, `finding_reviews`, `evidence_versions`, and `findings.raw_ai_text`.
- **Status**: resolved

### [Phase 5] [2026-10-13 16:45] — P1 Trust, Integrity & Model Limits
- **Cryptographic Pricing Input Hashing**: Updated `_compute_result_id` and `_compute_input_hash` to include rates, tiers, discounts, commitments, included units, exemptions, and original amounts, guaranteeing unique result IDs across varying pricing inputs.
- **LLM Fallback Transparency**: Added `produced_by` provenance tracking on findings (`llm_gemini` vs `llm_fallback`), and set investigation run status to `PARTIAL` whenever the LLM fallback is engaged. Production mode rejects empty keys and `LLM_MODE=mock`.
- **Strict LLM Output Validation**: Added `LLMFindingPayload` Pydantic model validating LLM JSON structures, verifying cited line result IDs against current engine results, rejecting unanchored monetary claims in narratives, and validating finding types.
- **Prompt Injection Defense Hardening**: Escaped closing delimiter tags (`&lt;/untrusted_customer_dispute&gt;`) and wrapped customer metadata in untrusted XML tags (`<untrusted_metadata>`).
- **Input Validation**: Enforced non-NaN/non-Inf float quantities (`allow_inf_nan=False`), validated `line_id` references against case invoice lines, expanded `event_id` column to `String(64)`, and added 409/422 responses.
- **Evidence Race Invalidation**: Added `UniqueConstraint("case_id", "version_number")` on `EvidenceVersion` and set in-flight investigation run status to `DISCARDED` if evidence versions change during execution.
- **Timing-Safe Auth**: Replaced direct token equality checks with `secrets.compare_digest` in `auth.py`.
- **Outcome**: All 98 unit and regression tests pass cleanly (1 skipped for live Postgres).
- **Status**: resolved



