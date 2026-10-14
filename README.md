# Billing Dispute Investigation & Resolution Agent

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)

A full-stack AI-assisted application designed to investigate, recalculate, and resolve SaaS and cloud billing disputes. The system pairs a deterministic pricing engine for financial math with an agentic investigation workflow, human-in-the-loop review, and immutable audit logging.

---

## 📑 Table of Contents

- [The Problem & Approach](#-the-problem--approach)
- [System Architecture](#-system-architecture)
- [Implemented Features (Phase 1 & Phase 2 Tested)](#-implemented-features-phase-1--phase-2-tested)
  - [1. Pure Deterministic Billing Engine](#1-pure-deterministic-billing-engine)
  - [2. Database Models & Schema](#2-database-models--schema)
  - [3. SQLite Append-Only Triggers](#3-sqlite-append-only-triggers)
  - [4. State Machine & Staleness Invalidation](#4-state-machine--staleness-invalidation)
  - [5. Human-in-the-Loop Finding Review](#5-human-in-the-loop-finding-review)
  - [6. Concurrency-Safe Idempotent Credit Approval](#6-concurrency-safe-idempotent-credit-approval)
  - [7. Bearer Token Auth & Roles](#7-bearer-token-auth--roles)
  - [8. Agentic Investigation Workflow (Phase 3)](#8-agentic-investigation-workflow-phase-3)
  - [9. Frontend Audit Workspace (Phase 4)](#9-frontend-audit-workspace-phase-4)
- [Excluded Scope](#-excluded-scope)
- [Known Limitations](#-known-limitations)
- [API Routes](#-api-routes)
- [Deployment](#-deployment)
- [Test Suite & Verification (98 Passing Tests)](#-test-suite--verification-98-passing-tests)
- [Quickstart & Local Setup](#-quickstart--local-setup)
- [Implementation Roadmap](#-implementation-roadmap)
- [Documentation & Engineering Logs](#-documentation--engineering-logs)

---

## 🎯 The Problem & Approach

In SaaS and metered cloud infrastructure billing, disputes regularly occur when customers identify discrepancies in multi-tier usage, minimum commitments, or environment-specific charges.

### Why Separate Calculation From Generative AI?
LLMs are probabilistic models prone to numerical errors and rounding inconsistencies when evaluating pricing tiers or calculating discounts. This architecture enforces a clear boundary:
- **Financial Calculation (Deterministic Engine):** Executed purely in Python using `Decimal`, integer cents, and explicit `ROUND_HALF_UP` rounding. The LLM does not calculate billing figures.
- **Investigation & Narration (Implemented - Phase 3):** An agentic workflow synthesizes narrative findings and drafts correspondence, citing cryptographic calculation result anchors (`result_id`).
- **Human Governance:** Financial credit issuance requires human reviewer approval.

---

## 🏛️ System Architecture

```
                                  ┌─────────────────────────────────────────┐
                                  │           FastAPI Web Service           │
                                  │               [IMPLEMENTED]             │
                                  └────────────────────┬────────────────────┘
                                                       │
         ┌─────────────────────────────────────────────┼─────────────────────────────────────────────┐
         ▼                                             ▼                                             ▼
┌─────────────────────────────────┐       ┌─────────────────────────────────┐       ┌─────────────────────────────────┐
│     Deterministic Engine        │       │      Agentic Investigation      │       │     Credit Approval Service     │
│         [IMPLEMENTED]           │       │          [IMPLEMENTED]          │       │          [IMPLEMENTED]          │
│  - Integer cents arithmetic     │       │  - LangGraph state graph        │       │  - Row-level lock concurrency   │
│  - Graduated vs Volume tiers    │       │  - Gemini API integration       │       │  - Cumulative credit cap check  │
│  - Included units & overage     │       │  - Result ID citation check     │       │  - SHA-256 idempotency key      │
│  - Malformed usage quarantine   │       │  - Finding reviews table        │       │  - 409 conflict handling        │
│  - SHA-256 result anchors       │       │  - Preserves raw vs edited text │       │  - Requires accepted finding    │
└────────────────┬────────────────┘       └────────────────┬────────────────┘       └────────────────┬────────────────┘
                 │                                         │                                         │
                 └─────────────────────────────────────────┼─────────────────────────────────────────┘
                                                           ▼
                                  ┌─────────────────────────────────────────┐
                                  │          Relational Storage             │
                                  │  - 14 SQLAlchemy ORM Tables [DONE]      │
                                  │  - SQLite foreign keys & WAL mode [DONE]│
                                  │  - SQLite append-only triggers [DONE]   │
                                  │  - PostgreSQL support configured [DONE] │
                                  └─────────────────────────────────────────┘
```

---

## ✅ Implemented Features (Phase 1 & Phase 2 Tested)

All items below are implemented in code and covered by passing automated unit tests:

### 1. Pure Deterministic Billing Engine
Implemented in [`backend/app/billing_engine.py`](backend/app/billing_engine.py):
- **Integer Cents Representation:** Stores all prices, billing quantities, and totals as integer cents ($10.00 = 1000$ cents) to prevent floating-point representation drift.
- **Boundary Rounding:** Uses Python's standard `Decimal` type with `ROUND_HALF_UP` applied once at the final line-item calculation boundary.
- **Supported Pricing Rules:**
  - `FLAT`: Fixed fee independent of event count.
  - `PER_UNIT`: Standard linear unit pricing.
  - `TIERED_GRADUATED`: Marginal tiering where usage spans multiple pricing brackets.
  - `TIERED_VOLUME`: Retroactive slab tiering where total volume determines the unit price for all units, with inclusive upper bounds.
  - `INCLUDED_UNITS`: Included allowance with dedicated overage rates.
  - `DISCOUNT_PCT`: Percentage discounts applied after base pricing.
  - `MINIMUM_COMMIT`: Spend floor enforcement evaluated after discounts.
- **Defensive Data Handling:**
  - **Quarantine:** Identifies negative usage values and isolates them into quarantined records without aborting the engine run; returns status `PARTIAL`.
  - **Ambiguity Branching:** When a tiered rule does not declare whether it is graduated or volume, the engine generates both concrete financial interpretations and sets status to `AMBIGUOUS`.
  - **Missing Rules:** Unmapped invoice lines return status `INSUFFICIENT_DATA`.
  - **Deterministic Result Anchors:** Emits an immutable `result_id` (`res_` + SHA-256 slice of normalized inputs) and overall `result_hash` for repeatability.

### 2. Database Models & Schema
Implemented in [`backend/app/models/`](backend/app/models/):
- 14 SQLAlchemy ORM models across [`case.py`](backend/app/models/case.py), [`invoice.py`](backend/app/models/invoice.py), [`usage.py`](backend/app/models/usage.py), [`calculation.py`](backend/app/models/calculation.py), [`investigation.py`](backend/app/models/investigation.py), and [`credit.py`](backend/app/models/credit.py).
- Foreign key constraints, lookup indexes, and JSON column mappings for tiered structures and environment exemption lists.
- `FindingReview` schema designed to store original AI text alongside separate reviewer modifications, notes, and approval status (`ACCEPT`, `EDIT`, `REJECT`).
- `Credit` schema with a `UNIQUE` constraint on `idempotency_key` and foreign key to `invoice_lines`.

### 3. SQLite Append-Only Triggers
Implemented in [`backend/app/database.py`](backend/app/database.py):
- Connect listener on SQLite enabling `PRAGMA foreign_keys = ON` and `PRAGMA journal_mode = WAL`.
- Physical database triggers installed on `case_events` and `calculation_line_results` that execute `SELECT RAISE(ABORT, '...')` on any attempted `UPDATE` or `DELETE` query, raising an `IntegrityError`.

### 4. State Machine & Staleness Invalidation
Implemented in [`backend/app/services/transition_service.py`](backend/app/services/transition_service.py):
- **Allowed transitions:**
  - `OPEN` $\rightarrow$ `AWAITING_INFO`, `RESOLVED`
  - `AWAITING_INFO` $\rightarrow$ `OPEN`, `RESOLVED`
  - `RESOLVED` $\rightarrow$ `REOPENED` *(reopening is only permitted from RESOLVED)*
  - `REOPENED` $\rightarrow$ `OPEN`, `AWAITING_INFO`, `RESOLVED`
- **Invalid transitions:** Returns HTTP **409 Conflict**.
- **Evidence versioning:** Uploading new evidence in *any* status increments `case.evidence_version`, flags all existing findings and resolution options as `is_stale = True`, and transitions status to `REOPENED` if arriving from `RESOLVED`.
- Appends immutable `STATUS_CHANGED` and `EVIDENCE_UPLOADED` audit events.

### 5. Human-in-the-Loop Finding Review
Implemented in [`backend/app/routers/findings.py`](backend/app/routers/findings.py):
- `POST /api/findings/{id}/review`: Supports `ACCEPT`, `EDIT`, and `REJECT`.
- Original raw AI text is permanently preserved; reviewer edits and notes are stored separately.
- Attributed with the reviewer identity and timestamp.

### 6. Concurrency-Safe Idempotent Credit Approval
Implemented in [`backend/app/services/credit_service.py`](backend/app/services/credit_service.py):
- **Concurrency Locking:** Acquires an exclusive row-level lock on the target invoice line (`SELECT FOR UPDATE` on PostgreSQL / `BEGIN IMMEDIATE` on SQLite).
- **Prerequisite Validation:** Rejects stale findings (HTTP 400) and requires an accepted human review (`ACCEPT`).
- **Cumulative Cap Invariant:** Enforces that requested credit does not exceed `eligible_overcharge - prior_credits - adjustments`. Cap exhaustion returns HTTP 400.
- **Idempotency:** Computes `SHA-256(case_id + invoice_line_id + reason_code)`. Duplicate requests return HTTP **409 Conflict**.

### 7. Bearer Token Auth & Roles
Implemented in [`backend/app/middleware/auth.py`](backend/app/middleware/auth.py):
- Inspects `Authorization: Bearer <token>` header. Missing or invalid tokens return HTTP 401 Unauthorized (`WWW-Authenticate: Bearer`).
- Roles: `REVIEWER` (mutating actions permitted) and `VIEWER` (read-only access; mutating attempts return HTTP 403 Forbidden).

---

### 8. Agentic Investigation & Multi-Provider LLM Resilience
Implemented in [`backend/app/agent/`](backend/app/agent/):
- **LangGraph StateGraph:** Multi-node execution pipeline (`gather_evidence` -> `run_calculation` -> `analyze_findings` -> `formulate_options` -> `validate_and_sanitize` -> `persist_results`).
- **Multi-Provider Fallback Hierarchy:**
  - Configurable fallback chain via `LLM_PROVIDERS` (default: `gemini,groq,openrouter`).
  - **GeminiProvider:** Primary provider using official `google-genai` SDK (`GEMINI_API_KEY`, `GEMINI_MODEL`).
  - **OpenAICompatProvider:** Resilient HTTP provider using `httpx` for Groq (`GROQ_API_KEY`, `GROQ_MODEL`) and OpenRouter (`OPENROUTER_API_KEY`, `OPENROUTER_MODEL`).
  - **Auto-Recovery on Schema Constraints:** If an open-weights model rejects `response_format={"type":"json_object"}` (HTTP 400), it automatically retries once without it and extracts JSON from markdown code fences.
- **Quota & Free-Tier Resilience:**
  - **HTTP 429 (Rate Limits) / 5xx Server Errors / Timeouts:** Waits 1s and retries once; on repeated failure, advances to next provider in sequence.
  - **HTTP 401/403 (Auth Errors) & 404 (Model Not Found):** Immediately skipped without retry.
  - **Malformed JSON:** If a provider produces non-JSON output, it is treated as a provider failure and immediately falls through to the next provider.
  - **Execution Deadline:** Total LLM execution time bounded to 40s per call.
- **Fail-Loud Guarantee (Never Mock in Real Mode):**
  - When `LLM_MODE=real`, the system strictly refuses to fabricate or mock AI findings.
  - If all providers fail: persists a `FAILED` `InvestigationRun`, writes an append-only `INVESTIGATION_RUN_FAILED` audit event to `case_events` with actor, sanitized reason, and attempts history, and returns **HTTP 502 Bad Gateway** with `{id, run_id, status: "FAILED", reason}`.
- **Traceability & Secret Isolation:**
  - Records provider name, model, token counts, and failure attempts list in `InvestigationRun.token_usage`.
  - Structured JSON logging (`logger="llm"`) with run ID, provider, model, attempt, latency, status, error type, and token counts. API keys, Authorization headers, and prompts are never logged.
  - Diagnostic CLI probe: `python backend/scripts/check_llm.py` pings all configured providers and reports latency/status without printing secrets.
  - Configuration status probe: `GET /api/llm/status` (any authenticated role) reports `configured` (bool) and model per provider.

### 9. Frontend Audit Workspace (Phase 4)
Implemented in [`frontend/`](frontend/):
- Modern dark-mode Single Page Application built with React 19, Vite, and custom CSS design tokens.
- Interactive dispute workspace featuring deterministic recalculation explorer, LangGraph AI investigation runner with live LLM provider badge (`LLM: provider (model)`), human review modal (`ACCEPT`, `EDIT`, `REJECT`), and credit approval panel.
- Demonstration presets for instant reproducible testing of multi-tier discrepancies, ambiguous contract rules, clean calculations, and prompt injection defense.

---

## 🚫 Excluded Scope

To maintain project focus and feasibility, the following areas are explicitly out of scope:
1. **Tax Calculation:** Tax logic, VAT, state sales taxes, and jurisdiction-specific tax exemptions are excluded.
2. **Real Payment Gateway Integration:** The application issues mock credit records for internal dispute resolution. It does not integrate with Stripe, Adyen, or banking rails.
3. **PDF / OCR Invoice Extraction:** Invoices and usage data are ingested via structured JSON and CSV formats, not via unstructured document OCR.
4. **ERP / Accounting Ledger Syncing:** Synchronization with external accounting platforms (NetSuite, QuickBooks) is not implemented.

---

## ⚠️ Known Limitations

1. **Database Triggers Scope:** While database triggers block application-level `UPDATE` and `DELETE` statements, a database administrator or privileged user with DDL permissions can drop triggers.
2. **Usage Quarantine Validation:** Current event quarantine checks for negative quantities, missing `line_id`/`event_id`, and non-string environment fields. It does not validate environments against an enforced whitelist enum.
3. **Single Discount Rule:** The engine currently supports a single percentage discount per line item. Multiple discounts on the same line trigger an `AMBIGUOUS` status.
4. **SQLite Concurrency:** Local development uses SQLite in WAL mode. Concurrency row-locking is designed for production PostgreSQL (`SELECT FOR UPDATE`).

---

## 🔌 API Routes

| Method | Endpoint | Description | Status |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/cases` | Create a new dispute case | **Implemented** |
| `GET` | `/api/cases` | List all dispute cases | **Implemented** |
| `GET` | `/api/cases/{id}` | Retrieve case details, lines, and rules | **Implemented** |
| `POST` | `/api/cases/{id}/transition` | Transition case status (returns 409 if invalid) | **Implemented** |
| `GET` | `/api/cases/{id}/events` | Retrieve immutable append-only audit trail | **Implemented** |
| `POST` | `/api/cases/{id}/evidence` | Upload usage evidence (bumps version, marks stale) | **Implemented** |
| `POST` | `/api/calculations/run` | Execute deterministic billing engine on evidence | **Implemented** |
| `GET` | `/api/calculations/{id}` | Retrieve calculation result by ID | **Implemented** |
| `POST` | `/api/cases/{case_id}/investigations` | Run autonomous LangGraph investigation (502 on failure) | **Implemented** |
| `GET` | `/api/cases/{case_id}/investigations` | List investigation runs for a case | **Implemented** |
| `GET` | `/api/investigations/{id}` | Retrieve full details of an investigation run | **Implemented** |
| `GET` | `/api/findings/case/{case_id}` | List findings and review history for a case | **Implemented** |
| `POST` | `/api/findings/{id}/review` | Submit human review (`ACCEPT`, `EDIT`, `REJECT`) | **Implemented** |
| `POST` | `/api/credits/approve` | Approve credit under row lock and cap check | **Implemented** |
| `GET` | `/api/credits/case/{case_id}` | List approved credits for a case | **Implemented** |
| `GET` | `/api/llm/status` | List LLM provider configuration status and model names | **Implemented** |
| `GET` | `/healthz` | Health check probe | **Implemented** |

---

## ☁️ Deployment

- **Blueprint Configuration:** Documented in [`render.yaml`](render.yaml) for Render Web Service deployment running Python 3.12 under Uvicorn.
- **Database Support:** SQLite WAL mode locally, Neon managed PostgreSQL in production with connection pool pre-ping.
- **Health Check Endpoint:** `GET /healthz` responds with HTTP 200 and application version.

---

## 🧪 Test Suite & Verification (112 Passing Tests, 1 Skipped)

The test suite runs under `pytest`:

```bash
LLM_MODE=mock pytest -v
```

### Breakdown of Test Results:
- `test_billing_engine.py`: 55 tests (pure deterministic arithmetic, tiers, included units, rounding, commitments, exemptions, quarantine)
- `test_models_and_db.py`: 10 tests (schema, foreign keys, append-only triggers, unique constraints, check constraints)
- `test_api_and_services.py`: 23 tests (case CRUD, evidence versioning, calculation API, human reviews, credit approval caps, idempotency)
- `test_agent.py`: 13 tests (LangGraph workflow, gates, prompt injection defense, citation validation, consistency checks)
- `test_concurrency.py`: 2 tests (10 concurrent threads hammering credit approvals, PostgreSQL SELECT FOR UPDATE test)
- `test_llm_resilience.py`: 9 tests (Gemini 429 quota fallback to Groq, 500 fallback to OpenRouter, 404 skips, invalid JSON fallback, response_format retry, secret isolation, HTTP 502 failure response, GET /api/llm/status)
- **Pricing & Calculation Logic (58 tests in [`backend/tests/test_billing_engine.py`](backend/tests/test_billing_engine.py)):**
  - Boundary rounding (`ROUND_HALF_UP`, half-away-from-zero).
  - Flat, per-unit, tiered graduated, and tiered volume calculations.
  - Included units with overage rate application.
  - Discounts and minimum spend commit floors applied to all interpretations.
  - Detection of uncovered usage when volume/graduated exceed last bounded tier (`INSUFFICIENT_DATA`).
  - Detection of multiple competing primary rules yielding `AMBIGUOUS` with 0 difference.
  - Environment exemptions and zero-billing verification.
  - Quarantine of negative usage quantities.
  - Repeatability and determinism of cryptographic `result_id` anchors and `result_hash` covering all pricing inputs.
- **Schema & Triggers (9 tests in [`backend/tests/test_models_and_db.py`](backend/tests/test_models_and_db.py)):**
  - Table creation verification for all 14 models.
  - Foreign key constraint rejection on SQLite.
  - Dialect-aware append-only triggers blocking `UPDATE` and `DELETE` on `case_events`, `calculation_line_results`, `credits`, `finding_reviews`, `evidence_versions`, and preserving `findings.raw_ai_text`.
  - Dialect-aware trigger generation for SQLite (`RAISE(ABORT)`) and PostgreSQL (`PL/pgSQL`).
  - Credit positive amount `CheckConstraint` (`amount_cents > 0`).
  - Unique constraint enforcement on `Credit.idempotency_key` and `EvidenceVersion(case_id, version_number)`.
  - JSON serialization of contract tiers and exemption lists.
- **FastAPI Backend & Services (25 tests in [`backend/tests/test_api_and_services.py`](backend/tests/test_api_and_services.py)):**
  - Auth enforcement: Bearer token validation with `secrets.compare_digest`, 401 on missing/invalid token, 403 on viewer mutating actions.
  - Startup security: Refuses to boot in production when default demo tokens are present or when `LLM_MODE=mock`.
  - Path traversal defense: SPA catch-all verifies realpath containment against `frontend/dist`.
  - State machine lifecycle transitions and 409 Conflict rejection on invalid paths.
  - Evidence upload bumping version from 1 to 2, marking findings stale, and reopening resolved cases.
  - Finding review workflows: `ACCEPT`, `EDIT` (with separate text), and `REJECT`.
  - End-to-end calculation execution via API with line-item results.
  - Credit approval: stale finding rejection (400), unreviewed finding rejection (400), line item mismatch rejection (400), ambiguous finding rejection (400), latest-review ordering (preventing ACCEPT-then-REJECT payment), idempotency 409 Conflict on repeat (preventing duplicate credit even when reason codes vary), and cumulative cap exhaustion (400).
  - Adjustment & cap validation: `invoice_line_id` reference checks (422 on invalid, 201 on valid/case-wide), case-wide cap enforcement via latest calculation join without inflation.
  - Investigation failure audit: FAILED runs return HTTP 200 with status=FAILED and record `INVESTIGATION_RUN_FAILED` in audit events.
- **LangGraph Agentic Investigation (10 tests in [`backend/tests/test_agent.py`](backend/tests/test_agent.py)):**
  - Autonomous multi-node graph: gather evidence, deterministic calculation, findings synthesis, resolution formulation.
  - Injection defense with escaped `<untrusted_customer_dispute>` isolation tags and untrusted metadata wrapping.
  - Pydantic schema validation (`LLMFindingPayload`), citation verification, and narrative financial amount consistency checks.
  - Fail-loud error handling: LLM transient failures yield `FAILED` status, logging `INVESTIGATION_RUN_FAILED` without producing fabricated mock findings.
- **Concurrency Stress Test (1 test in [`backend/tests/test_concurrency.py`](backend/tests/test_concurrency.py)):**
  - Fires 10 concurrent threads simultaneously against a single overcharge line item.
  - Proves that exactly 1 thread claims the credit, 9 competing threads are rejected, and total approved credits strictly equals the eligible overcharge (zero double-crediting).
  - PostgreSQL `SELECT FOR UPDATE` verification configured via `POSTGRES_TEST_URL` (conditionally skipped pending live PG connection).

---

## 🚀 Quickstart & Local Setup

### 1. Clone & Enter Directory
```bash
git clone https://github.com/abhi-1289-9821/async-task.git
cd async-task
```

### 2. Configure Environment
```bash
cp .env.example .env
```
Edit `.env` as needed:
```ini
DATABASE_URL=sqlite:///./billing_disputes.db
ENVIRONMENT=development
PORT=8000
DEBUG=false
DEMO_REVIEWER_TOKEN=your-reviewer-token-here
DEMO_VIEWER_TOKEN=your-viewer-token-here
GEMINI_API_KEY=your-gemini-api-key-here
GEMINI_MODEL=gemini-2.0-flash
LLM_MODE=real
```

### 3. Setup Virtual Environment
```bash
cd backend
python -m venv .venv

# On Windows:
.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
```

### 4. Run Test Suite
```bash
pytest -v
```

### 5. Launch Frontend UI
```bash
cd ../frontend
npm install
npm run dev
# Access UI at http://localhost:5173
```

---

## 🗺️ Implementation Roadmap

- [x] **Phase 0: Architecture & Risk Evaluation**
- [x] **Phase 1: Deterministic Engine & Core Schema** (60 passing tests)
- [x] **Phase 2: Database Layer, Audit Trail & State Transitions** (Schema constraints, triggers, immutability, concurrency locking)
- [x] **Phase 3: Agentic Investigation (LangGraph + Gemini)** (86 passing tests, citation & injection defense)
- [x] **Phase 4: Frontend Audit Workspace (React + Vite)** (Dark mode UI, scenario presets, interactive review)
- [x] **Phase 5: End-to-End Scenarios & Demonstration Workflows** (99+ passing tests, live API & UI verification)

---

## 📚 Documentation & Engineering Logs

- **Engineering Audit Log:** [`docs/agent_log.md`](docs/agent_log.md) records all development decisions, dependency adjustments, and test corrections chronologically.
- **Agent Usage Guide:** Available in [`docs/AGENT_USAGE.md`](docs/AGENT_USAGE.md) detailing architecture, security controls, and operational workflows.
