# Agent Usage & Collaboration Record

This document records the complete, transparent record of how autonomous agentic coding tools were utilized to build, harden, and verify the **Billing Dispute Resolution & Autonomous Investigation System**. It documents the development tooling, representative user prompts, delegated implementation tasks, chronological mistakes and user corrections, and verification methodologies.

---

## 1. Tools & Development Environment

The project was constructed using the **Antigravity Agentic IDE** paired with the following local and cloud toolchains:

| Tool / Environment | Purpose |
| :--- | :--- |
| **Python 3.12 (venv)** | Core backend runtime, chosen over 3.14 for LangGraph/FastAPI ecosystem compatibility. |
| **FastAPI & Uvicorn** | High-performance asynchronous REST API framework serving backend endpoints and SPA static assets. |
| **LangGraph 1.2+ & Google GenAI SDK** | Multi-node `StateGraph` workflow engine orchestrating evidence gathering, calculation, and Gemini-based reasoning. |
| **SQLAlchemy 2.0 & Alembic** | ORM data modeling, composite foreign keys, and repeatable database schema migrations. |
| **SQLite (WAL) & PostgreSQL** | Dual-dialect database support with append-only database triggers (`RAISE(ABORT)` on SQLite, PL/pgSQL on Postgres). |
| **Node.js 20 & Vite / React** | Frontend client development, building an optimized, secret-free single page application (SPA). |
| **Pytest & Pytest-Asyncio** | Automated test suite execution across 103 test cases. |
| **Browser Subagent (Playwright)** | Headless interactive browser automation for UI visual inspection and end-to-end user journey validation. |
| **Ripgrep (`grep_search`) & AST Scanners** | Codebase inspection, symbol tracking, and bundle secret audits. |

---

## 2. Representative Prompts & User Instructions

Development proceeded across six major phases driven by strict architectural and financial constraints:

### Phase 0: Workspace Setup & Invariant Definition
> *"Workspace inspection and proposal review: Enforce Python 3.12; never assume model names (keep configurable); store human reviews separately from original AI text; enforce SQLite BEGIN IMMEDIATE and Postgres SELECT FOR UPDATE for concurrency locking; state machine invalid transitions must return 409 Conflict; append-only triggers on case_events; math must use Python Decimal with ROUND_HALF_UP only at line boundaries; LLMs must never calculate dollars."*

### Phase 1: Pure Deterministic Billing Engine
> *"Implement the deterministic billing engine in pure Python with zero database or LLM dependencies. Support Flat, Per-Unit, Tiered (Graduated & Volume), Included Units, Discounts, Minimum Commitments, and Environment Exemptions. Generate deterministic result_id hashes based on all pricing inputs."*

### Phase 2: REST API, Audit Logs & Concurrency Locking
> *"Implement the database schema and REST API endpoints for Cases, Evidence, Calculations, Reviews, and Credits. Implement append-only triggers on audit tables. Guarantee that 10 concurrent credit requests for the same line item cannot double-credit or exceed the cumulative cap."*

### Phase 3: Autonomous LangGraph Investigation & Injection Safety
> *"Implement an autonomous LangGraph StateGraph. Untrusted customer statements must be isolated inside `<untrusted_customer_dispute>` delimiters. System instructions must prevent prompt injection and hallucinated dollar amounts. AI findings must cite deterministic engine result_ids. Implement validators for citations and consistency."*

### Phase 4: Full-Stack React + Vite UI
> *"Build a modern, responsive web application for dispute investigation. Provide case list, detailed breakdown, manual calculation runner, investigation triggering, human review modal, and credit approval. Never bake tokens into frontend bundles."*

### Phase 5 & Regressions: Financial Integrity & Security Hardening
> *"Fix regressions: add invoice_line_id to AdjustmentCreate; join Calculation to compute case-wide cap from latest calculation without AttributeError; rewrite Alembic migration from empty database; remove reason_code from credit idempotency key to prevent double-crediting via reason switching; record INVESTIGATION_RUN_FAILED on run failure and return HTTP 200; add dispute_description to case creation and UI."*

### Phase 6: Multi-Provider LLM Resilience & Free-Tier Quota Fallback
> *"Make the live LLM call resilient to free-tier quota limits by trying providers in this order: Gemini (primary) -> Groq -> OpenRouter. Never fabricate or mock output when LLM_MODE=real. Implement providers.py (GeminiProvider, OpenAICompatProvider via httpx), ordered fallback on 429/5xx/timeout with 1s retry, immediate skip on 401/403/404, 40s deadline, fail-loud 502 with run id and reason on total failure, trace provider/model in token_usage and UI badge, structured JSON logging without secrets, GET /api/llm/status, and backend/scripts/check_llm.py."*

---

## 3. Delegated Agent Workflows

The human engineer delegated substantial portions of the architectural and implementation workloads to the agent:

1. **Deterministic Financial Math Implementation**: Scaffolding `billing_engine.py` with `Decimal` arithmetic, boundary condition handling (such as exact boundary unit classification in volume vs graduated tiers), discount application order, and spend commitments.
2. **Database Modeling & Dialect-Specific Triggers**: Creating SQLAlchemy 2.0 mapped models with composite primary keys (`cases.id`, `invoice_lines.id`) and writing dialect-aware DDL triggers preventing updates/deletions on audit logs (`case_events`, `credits`, `calculation_line_results`, `finding_reviews`).
3. **LangGraph StateGraph Orchestration**: Constructing the 6-node state machine (`gather_evidence` -> `run_calculation` -> `analyze_findings` -> `formulate_options` -> `validate_and_sanitize` -> `persist_results`) with conditional routing.
4. **Automated Test Suite Expansion**: Authoring comprehensive test suites (`test_billing_engine.py`, `test_models_and_db.py`, `test_agent.py`, `test_api_and_services.py`, `test_concurrency.py`) totaling 103 passing tests.
5. **Frontend UI Assembly**: Developing the React SPA interface with glassmorphism design tokens, token authentication modal, interactive case inspector, and evidence ingestion forms.
6. **Alembic Schema Generation**: Producing clean, greenfield migration revisions generating the complete multi-tenant database schema from scratch.

---

## 4. Agent Mistakes, Incorrect Assumptions & Corrections

Transparency regarding AI mistakes and human corrections is an essential requirement. The following chronological log documents every significant error made by the agent and how it was corrected:

### 1. Python 3.14 Premature Adoption
- **Mistake**: The agent initially proposed using the system-installed Python 3.14.0.
- **Correction**: LangGraph and FastAPI dependencies were incompatible with Python 3.14 pre-release builds. The user corrected the agent to create a dedicated Python 3.12 virtual environment (`.venv`).

### 2. Dependency Pin Clashes (`langchain-core` & `pydantic`)
- **Mistake**: The agent initially pinned `langchain-core==0.3.25` and `pydantic==2.10.3`, which conflicted with `langgraph==1.2.15` (requiring `langchain-core>=1.4.7`) and `google-genai` (requiring `pydantic>=2.12.5`).
- **Correction**: Resolved pins to semantic version ranges (`langchain-core>=1.4.7,<2.0.0` and `pydantic>=2.12.5,<3.0.0`), verified via dry-run installation.

### 3. Incorrect `ROUND_HALF_UP` Negative Value Assertion
- **Mistake**: In unit testing, the agent asserted that `_round_cents(Decimal('-0.5')) == 0`.
- **Correction**: In Python standard library `Decimal.quantize(..., rounding=ROUND_HALF_UP)`, `-0.5` rounds away from zero to `-1`. The test assertion was corrected and documented.

### 4. Database Trigger Exception Type Mismatch
- **Mistake**: The agent expected SQLite `RAISE(ABORT)` triggers to raise `sqlite3.OperationalError`.
- **Correction**: SQLite DB-API translates `RAISE(ABORT)` into `sqlite3.IntegrityError` (wrapped by SQLAlchemy as `sqlalchemy.exc.IntegrityError`). Test suites were updated to assert `IntegrityError`.

### 5. Dataclass & Model Field Signature Mismatches
- **Mistake**: In Phase 2, the agent passed `timestamp` to `engine.UsageEvent` (which only takes `event_id`, `line_id`, `quantity`, `environment`) and used `engine.PricingTier` instead of `engine.TierBand`. Additionally, it attempted to insert a string into `EvidenceVersion.id` (an autoincrement integer).
- **Correction**: Removed timestamp from pure calculation dataclasses, imported `TierBand`, and allowed database autoincrement for evidence version primary keys.

### 6. Fragile Assumption of Model Names
- **Mistake**: The agent attempted to hardcode default model names (`gemini-2.5-flash`), which were deprecated or unavailable.
- **Correction**: Refactored `llm_client.py` and `config.py` to treat `GEMINI_MODEL` strictly as an external environment variable configuration with fallback to `gemini-3.1-flash-lite`, and supported explicit user overrides.

### 7. Reviewer Token Leaked into Client JS Bundle
- **Mistake**: The frontend build script initially read `VITE_DEMO_REVIEWER_TOKEN` during `npm run build`, baking the default reviewer Bearer token into static assets.
- **Correction**: Completely removed `VITE_DEMO_REVIEWER_TOKEN` and `VITE_DEMO_VIEWER_TOKEN` from the build environment. The frontend now loads with an unauthenticated state and provides a secure "Set Reviewer Token" modal stored strictly in client memory/session storage. Verified with AST string scanning (0 tokens in bundle).

### 8. Directory Traversal in SPA Static File Server
- **Mistake**: The FastAPI SPA fallback route used simple path joining (`frontend/dist / full_path`) without verifying that the resolved path remained inside the static distribution directory.
- **Correction**: Implemented `os.path.realpath` prefix verification. Any request attempting to traverse outside `frontend/dist` (e.g. `/../../backend/requirements.txt`) is blocked and redirected to `index.html`. Added regression test `test_path_traversal_blocked_on_spa_route`.

### 9. Wrong-Line Credit Approval Vulnerability
- **Mistake**: `credit_service.py` validated that the finding was accepted and non-stale, but did not verify that `line_result.line_id == invoice_line_id`. A reviewer could approve credit on line B using an accepted finding from line A.
- **Correction**: Added strict equality check `line_result.line_id == invoice_line_id` returning HTTP 400 "Invoice line mismatch". Added regression test `test_credit_rejected_when_invoice_line_mismatches_calculation_result`.

### 10. Credit Approval on Ambiguous Findings
- **Mistake**: When multiple competing contract rules produced an `AMBIGUOUS` calculation, the agent formulated resolution options, and the credit endpoint permitted approving credits on the non-zero difference.
- **Correction**: Enforced `finding.finding_type == CONFIRMED_CALCULATION_DISCREPANCY` and `line_result.finding_type == CONFIRMED_CALCULATION_DISCREPANCY` in `credit_service.py`. Enforced `difference_cents = 0` on ambiguous lines in `billing_engine.py`.

### 11. Review Ordering (ACCEPT-then-REJECT Bypassed)
- **Mistake**: `credit_service.py` queried for *any* historical review with `action == "ACCEPT"`. If an operator accepted a finding and subsequently rejected it, credit could still be approved.
- **Correction**: Changed the query to inspect strictly the *latest* review sorted by `created_at DESC, id DESC`.

### 12. Missing `invoice_line_id` on `AdjustmentCreate` (500 Error)
- **Mistake**: `cases.py` read `adj.invoice_line_id`, but `AdjustmentCreate` in `schemas/case.py` lacked the field, crashing any case creation containing adjustments with HTTP 500.
- **Correction**: Added `invoice_line_id: Optional[str] = None` to `AdjustmentCreate` and `AdjustmentResponse`, added reference validation against `case.invoice_lines`, and added regression test `test_case_with_adjustments_and_line_id_validation`.

### 13. Case-Wide Credit Cap Query Crash (`AttributeError`)
- **Mistake**: `credit_service.py` filtered on `CalculationLineResult.case_id`, a column that did not exist on `CalculationLineResult` (which belongs to `Calculation`). In addition, re-running calculations caused multiple runs to be summed, artificially inflating the cumulative cap.
- **Correction**: Joined `Calculation` via `.join(Calculation, Calculation.id == CalculationLineResult.calculation_id)` and filtered strictly to the latest calculation (`latest_calc.id`). Added regression test `test_case_wide_credit_cap_enforced_via_latest_calculation_join`.

### 14. Idempotency Key Reason Code Collision Bypass
- **Mistake**: The credit idempotency key was computed as `sha256(case_id:line_id:finding_id:reason_code)`. Because the UI offers multiple reason codes, an operator could approve the same finding multiple times simply by selecting a different reason code from the dropdown.
- **Correction**: Removed `reason_code` from the hash: `sha256(f"{case_id}:{invoice_line_id}:{finding_id or ''}")`. Any subsequent attempt to credit the same finding immediately raises HTTP 409 Conflict. Added regression test `test_credit_approval_success_and_repeat_409_conflict`.

### 15. Silent Handling of Investigation Failures
- **Mistake**: Failed agent runs did not write an audit event, the endpoint returned HTTP 201, and the README documented an obsolete `PARTIAL` mock fallback.
- **Correction**: On failure, `graph.py` writes a `CaseEvent` of type `INVESTIGATION_RUN_FAILED`, the router returns HTTP 200 with `status="FAILED"`, and the README was updated to reflect strict fail-loud behavior. Added regression test `test_failed_investigation_run_writes_audit_event_and_returns_status_failed`.

### 16. Test Mock Incompatibility via Extra `run_id` Keyword Argument
- **Mistake**: When adding observability tracing to `call_llm`, the agent added `run_id=state.get("run_id")` keyword argument to `call_llm(prompt, ...)` call sites. Existing adversarial tests monkeypatching `call_llm` with positional-only lambda signatures crashed with `unexpected keyword argument 'run_id'`.
- **Correction**: Updated `call_llm` to accept `**kwargs` with backwards-compatible defaults, invoked `call_llm` positionally in finding/option generators, and resolved `run_id` from context.

---

## 5. Verification Methodologies

Every feature and bugfix was verified through multi-layered automated and manual validations:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        VERIFICATION LAYERS                             │
├────────────────────────────────┬───────────────────────────────────────┤
│ 1. Deterministic Unit Tests    │ 112 tests in pytest (Decimal math,    │
│                                │ rounding, tiers, quarantine, caps)    │
├────────────────────────────────┼───────────────────────────────────────┤
│ 2. Concurrency Stress Probing  │ 10 concurrent threads hammering credit│
│                                │ approvals (verified zero double credit│
├────────────────────────────────┼───────────────────────────────────────┤
│ 3. Database Triggers & DDL     │ Tested RAISE(ABORT) and PL/pgSQL      │
│                                │ triggers blocking UPDATE/DELETE       │
├────────────────────────────────┼───────────────────────────────────────┤
│ 4. Secret & Bundle AST Scans   │ Grep & regex scan of Vite dist bundle │
│                                │ (confirmed 0 tokens in bundle)        │
├────────────────────────────────┼───────────────────────────────────────┤
│ 5. Migration Greenfield Tests  │ Executed 'alembic upgrade head' on    │
│                                │ clean SQLite and verified all tables  │
├────────────────────────────────┼───────────────────────────────────────┤
│ 6. End-to-End Browser Probes   │ Playwright browser agent verifying UI │
│                                │ modals, citation badges, case creation│
└────────────────────────────────┴───────────────────────────────────────┘
```

1. **Deterministic Test Suite Execution**:
   - `pytest backend/tests` executes 112 automated tests across engine math, model constraints, agent validator, API routes, multi-provider resilience, and concurrency.
2. **Concurrency Verification**:
   - `tests/test_concurrency.py` launches 10 concurrent Python threads attempting to approve credit for the same $30.00 discrepancy. Asserts that exactly 1 request succeeds (HTTP 201) while 9 requests are rejected with 409 Conflict or 400 Cap Exceeded, leaving the database credit total at exactly 3000 cents.
3. **Trigger Immutability Verification**:
   - Explicit tests attempt to execute `UPDATE` and `DELETE` SQL queries against `case_events` and `calculation_line_results`, confirming that the database engine aborts the transaction with `IntegrityError`.
4. **Secret Scanning**:
   - Built frontend using `npm run build` and executed regex searches for `demo-reviewer-token`, `demo-viewer-token`, and `API_KEY` across `frontend/dist/assets/*.js`. Zero instances found.
5. **Fresh Database Migrations**:
   - Deleted local databases, ran `alembic upgrade head`, and confirmed clean migration table creation and successful execution of `seed_demo_data.py`.
