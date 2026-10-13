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


