# Billing Dispute Investigation & Resolution Agent

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)

A full-stack AI-assisted application designed to investigate, recalculate, and resolve SaaS and cloud billing disputes. The system pairs a deterministic pricing engine for financial math with an agentic investigation workflow, human-in-the-loop review, and immutable audit logging.

---

## 📑 Table of Contents

- [The Problem & Approach](#-the-problem--approach)
- [System Architecture](#-system-architecture)
- [Implemented Features (Phase 1 Tested)](#-implemented-features-phase-1-tested)
  - [1. Pure Deterministic Billing Engine](#1-pure-deterministic-billing-engine)
  - [2. Database Models & Schema](#2-database-models--schema)
  - [3. SQLite Append-Only Triggers](#3-sqlite-append-only-triggers)
- [Planned Features (Phase 2 & Phase 3)](#-planned-features-phase-2--phase-3)
- [Excluded Scope](#-excluded-scope)
- [Known Limitations](#-known-limitations)
- [API Routes (Pending Phase 2)](#-api-routes-pending-phase-2)
- [Deployment (Pending Phase 2)](#-deployment-pending-phase-2)
- [Test Suite & Verification](#-test-suite--verification)
- [Quickstart & Local Setup](#-quickstart--local-setup)
- [Documentation & Engineering Logs](#-documentation--engineering-logs)

---

## 🎯 The Problem & Approach

In SaaS and metered cloud infrastructure billing, disputes regularly occur when customers identify discrepancies in multi-tier usage, minimum commitments, or environment-specific charges.

### Why Separate Calculation From Generative AI?
LLMs are probabilistic models prone to numerical errors and rounding inconsistencies when evaluating pricing tiers or calculating discounts. This architecture enforces a clear boundary:
- **Financial Calculation (Deterministic Engine):** Executed purely in Python using `Decimal`, integer cents, and explicit `ROUND_HALF_UP` rounding. The LLM does not calculate billing figures.
- **Investigation & Narration (Planned - Phase 3):** An agentic workflow synthesizes narrative findings and drafts correspondence, citing cryptographic calculation result anchors (`result_id`).
- **Human Governance:** Financial credit issuance requires human reviewer approval.

---

## 🏛️ System Architecture

```
                                  ┌─────────────────────────────────────────┐
                                  │           FastAPI Web Service           │
                                  │           (Pending - Phase 2)           │
                                  └────────────────────┬────────────────────┘
                                                       │
         ┌─────────────────────────────────────────────┼─────────────────────────────────────────────┐
         ▼                                             ▼                                             ▼
┌─────────────────────────────────┐       ┌─────────────────────────────────┐       ┌─────────────────────────────────┐
│     Deterministic Engine        │       │      Agentic Investigation      │       │     Credit Approval Service     │
│       [IMPLEMENTED]             │       │      (Planned - Phase 3)        │       │       (Planned - Phase 2)       │
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
                                  │  - PostgreSQL migrations (Phase 2)      │
                                  └─────────────────────────────────────────┘
```

---

## ✅ Implemented Features (Phase 1 Tested)

All items below are implemented in code and covered by passing unit tests:

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
- `Credit` schema with a `UNIQUE` constraint on `idempotency_key`.

### 3. SQLite Append-Only Triggers
Implemented in [`backend/app/database.py`](backend/app/database.py):
- Connect listener on SQLite enabling `PRAGMA foreign_keys = ON` and `PRAGMA journal_mode = WAL`.
- Physical database triggers installed on `case_events` and `calculation_line_results` that execute `SELECT RAISE(ABORT, '...')` on any attempted `UPDATE` or `DELETE` query, raising an `IntegrityError`.

---

## ⏳ Planned Features (Phase 2 & Phase 3)

The following components are designed in the architecture but are not yet implemented or tested:

- **State Machine Transitions (Planned - Phase 2):** Enforcing allowed transitions between `OPEN`, `AWAITING_INFO`, `RESOLVED`, and `REOPENED`, returning HTTP 409 on invalid transitions.
- **Staleness Tracking & Rejection (Planned - Phase 2):** Marking findings stale on evidence version increments and rejecting credit approvals linked to stale findings.
- **Credit Concurrency Locking (Planned - Phase 2):** Transaction locking (`SELECT FOR UPDATE` on PostgreSQL / `BEGIN IMMEDIATE` on SQLite) to enforce cumulative credit caps during concurrent approval attempts.
- **Duplicate Credit 409 Responses (Planned - Phase 2):** Returning HTTP 409 Conflict when an idempotency key matches an existing record.
- **PostgreSQL DDL Triggers (Planned - Phase 2):** Translating the append-only SQLite triggers into PostgreSQL PL/pgSQL trigger functions via Alembic migrations.
- **Agentic Investigation Graph (Planned - Phase 3):** LangGraph multi-node orchestrator using the Google Gemini API with fallback mock mode for testing, citation verification, and evidence-gathering abort logic.
- **Frontend Workspace (Planned - Phase 4):** React / Vite UI with timeline views, discrepancy diffing, and reviewer approval controls.

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
4. **SQLite Concurrency:** Local development uses SQLite in WAL mode. High-concurrency operations will be verified against PostgreSQL.

---

## 🔌 API Routes (Pending Phase 2)

The following REST API endpoints are designed and will be implemented in Phase 2:

| Method | Endpoint | Description | Status |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/cases` | Create a new dispute case | *Pending (Phase 2)* |
| `GET` | `/api/cases/{id}` | Retrieve case details, lines, and events | *Pending (Phase 2)* |
| `POST` | `/api/cases/{id}/transition` | Transition case status (returns 409 if invalid) | *Pending (Phase 2)* |
| `POST` | `/api/cases/{id}/evidence` | Upload new usage evidence, increments version | *Pending (Phase 2)* |
| `POST` | `/api/calculations/run` | Execute deterministic recalculation on evidence | *Pending (Phase 2)* |
| `POST` | `/api/findings/{id}/review` | Submit human review (`ACCEPT`, `EDIT`, `REJECT`) | *Pending (Phase 2)* |
| `POST` | `/api/credits/approve` | Approve mock credit under row lock and cap check | *Pending (Phase 2)* |

---

## ☁️ Deployment (Pending Phase 2)

Deployment configuration is planned for Phase 2:
- **Backend Service:** Render Web Service running FastAPI under Python 3.12 via Uvicorn.
- **Database:** Managed PostgreSQL instance on Neon.
- **Configuration:** Documented in `render.yaml` with automated health-check endpoints.

---

## 🧪 Test Suite & Verification

The test suite runs under `pytest`:

```bash
pytest -v
```

### 60 Passing Tests (Phase 1):
- **Pricing & Calculation Logic (53 tests in [`backend/tests/test_billing_engine.py`](backend/tests/test_billing_engine.py)):**
  - Boundary rounding (`ROUND_HALF_UP`, half-away-from-zero).
  - Flat, per-unit, tiered graduated, and tiered volume calculations.
  - Included units with overage rate application.
  - Discounts and minimum spend commit floors.
  - Environment exemptions and zero-billing verification.
  - Quarantine of negative usage quantities.
  - Dual interpretation generation for unspecified tier types.
  - Repeatability and determinism of cryptographic `result_id` anchors.
- **Schema & Triggers (7 tests in [`backend/tests/test_models_and_db.py`](backend/tests/test_models_and_db.py)):**
  - Table creation verification for all 14 models.
  - Foreign key constraint rejection on SQLite.
  - Append-only trigger verification blocking `UPDATE` on `case_events`.
  - Append-only trigger verification blocking `DELETE` on `case_events`.
  - Append-only trigger verification blocking modifications on `calculation_line_results`.
  - Unique constraint enforcement on `Credit.idempotency_key`.
  - JSON serialization of contract tiers and exemption lists.

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

---

## 📚 Documentation & Engineering Logs

- **Technical Interview Prep:** [`INTERVIEW_PREP.md`](INTERVIEW_PREP.md) contains detailed questions, answers, and trade-off discussions.
- **Engineering Audit Log:** [`docs/agent_log.md`](docs/agent_log.md) records all development decisions, dependency adjustments, and test corrections chronologically.
- **Agent Usage Summary:** Finalized in [`docs/AGENT_USAGE.md`](docs/AGENT_USAGE.md) at the conclusion of Phase 5.
