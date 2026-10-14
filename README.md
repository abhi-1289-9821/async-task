# FairBill — Autonomous Billing Dispute Investigation & Governance Agent

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)
[![React 19](https://img.shields.io/badge/React-19-61dafb.svg)](https://react.dev/)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.2+-purple.svg)](https://langchain-ai.github.io/langgraph/)

A full-stack, AI-assisted platform engineered to investigate, recalculate, and resolve SaaS and cloud billing disputes. The system pairs a **pure deterministic pricing engine** for financial mathematics with an **autonomous LangGraph investigation agent**, human-in-the-loop review, and immutable audit logging.

---

## 🌐 Live Demo & Deployment Credentials

> [!NOTE]
> The tokens below are **demo-only credentials** provisioned for reviewer evaluation on this deployment. Real production deployments require custom high-entropy secrets set via environment variables.

- **Deployed Live URL:** `https://billing-dispute-agent.onrender.com` *(or local: `http://localhost:5173`)*
- **Demo Reviewer Token:** `demo-reviewer-token-2026` *(permissions: run calculations, trigger investigations, review findings, approve credits, upload amendments)*
- **Demo Viewer Token:** `demo-viewer-token-2026` *(permissions: read-only access to dispute cases, audit logs, and calculation breakdowns)*

---

## 📑 Table of Contents

- [The Problem & Architectural Invariants](#-the-problem--architectural-invariants)
- [System Architecture](#-system-architecture)
- [Auto-Seeded Demonstration Cases](#-auto-seeded-demonstration-cases)
- [Step-by-Step Reviewer Walkthrough](#-step-by-step-reviewer-walkthrough)
- [Core Features & Engineering Implementation](#-core-features--engineering-implementation)
- [Scope: Completed vs Excluded](#-scope-completed-vs-excluded)
- [Known Limitations](#-known-limitations)
- [API Route Reference](#-api-route-reference)
- [Deployment & Database Migrations](#-deployment--database-migrations)
- [Automated Test Suite (143 Passed, 1 Skipped)](#-automated-test-suite-143-passed-1-skipped)
- [Local Setup & Verification](#-local-setup--verification)

---

## 🎯 The Problem & Architectural Invariants

Metered cloud and SaaS disputes arise when customer telemetry conflicts with complex contractual terms: graduated vs volume pricing brackets, environment exemptions (staging vs production), minimum spend commitments, and percentage discounts.

### Non-Negotiable Ground Rules
1. **Deterministic Financial Math Only**: Money is calculated strictly in Python using standard library `Decimal`, integer cents ($10.00 = 1000$ cents), and `ROUND_HALF_UP` boundary rounding in [`backend/app/billing_engine.py`](backend/app/billing_engine.py). **The LLM never computes, invents, or changes financial figures.**
2. **AI Reasoner & Narrator**: LangGraph and LLM providers formulate structured findings, explanation hypotheses, and proposed resolutions, citing immutable cryptographic result IDs (`result_id`).
3. **Fail-Loud Guarantee (No Mocking in Production)**: When `LLM_MODE=real`, the system never fakes or fabricates AI findings. If upstream providers fail or timeout, the run transitions to `FAILED`, appends an `INVESTIGATION_RUN_FAILED` audit event, and returns **HTTP 502 Bad Gateway**. If no LLM provider is configured, it returns **HTTP 503 Service Unavailable**.
4. **Zero Bundle Secrets**: Client tokens are strictly user-supplied or loaded from session/local storage. No demo tokens or API keys exist in client build bundles.

---

## 🏛️ System Architecture

```
                                  ┌─────────────────────────────────────────┐
                                  │           FastAPI REST Service          │
                                  │   (Auth, Routers, Lifespan Auto-Seed)   │
                                  └────────────────────┬────────────────────┘
                                                       │
         ┌─────────────────────────────────────────────┼─────────────────────────────────────────────┐
         ▼                                             ▼                                             ▼
┌─────────────────────────────────┐       ┌─────────────────────────────────┐       ┌─────────────────────────────────┐
│     Deterministic Engine        │       │      Agentic Investigation      │       │     Credit Approval Service     │
│   (backend/app/billing_engine)  │       │     (LangGraph Multi-Node)      │       │   (backend/app/credit_service)  │
│  - Integer cents arithmetic     │       │  - Multi-provider fallback      │       │  - Row-level lock concurrency   │
│  - Graduated vs Volume slabs    │       │  - Per-line finding synthesis   │       │  - Shared compute_remaining_cap │
│  - Included units & overage     │       │  - Citation & amount validators │       │  - SHA-256 idempotency key      │
│  - Environment & period filters │       │  - Engine-derived finding types │       │  - 409 Conflict on duplicates   │
│  - SHA-256 result anchors       │       │  - 180s TTL abandoned reaper    │       │  - Requires accepted finding    │
└────────────────┬────────────────┘       └────────────────┬────────────────┘       └────────────────┬────────────────┘
                 │                                         │                                         │
                 └─────────────────────────────────────────┼─────────────────────────────────────────┘
                                                           ▼
                                  ┌─────────────────────────────────────────┐
                                  │       Relational Storage & Audit        │
                                  │  - 14 SQLAlchemy ORM Tables             │
                                  │  - Partial Unique Index on RUNNING runs │
                                  │  - Append-only DDL triggers             │
                                  │  - Alembic migrations & create_all      │
                                  └─────────────────────────────────────────┘
```

---

## 📦 Auto-Seeded Demonstration Cases

On startup against an empty database, `backend/app/seed.py` idempotently seeds three foundational dispute scenarios:

1. **`case-acme-101` — Metered API Tier Overcharge (Confirmed Discrepancy)**
   - **Contract Rule:** `PER_UNIT` at 10 cents/unit; `exempt_environments: ["staging", "test"]`.
   - **Billed Amount:** $50.00 (5000 cents).
   - **Usage Telemetry:** 250 production units + 150 staging units.
   - **Prior Adjustment:** One line-item adjustment of $5.00 (500 cents).
   - **What it demonstrates:** Deterministic environment filtering (staging exempt), calculation discrepancy ($25.00 vs $50.00 billed = $25.00 overcharge), and cumulative credit cap deduction ($25.00 eligible - $5.00 prior adjustment = **$20.00 remaining cap**).
2. **`case-bravo-102` — Competing Tiered Clauses (Contract Ambiguity)**
   - **Contract Rule:** Competing `TIERED_GRADUATED` and `TIERED_VOLUME` rules on the same line (tier 1: up to 100 @ 15c; tier 2: unbounded @ 10c).
   - **Billed Amount:** $40.00 (4000 cents).
   - **Usage Telemetry:** 200 production units.
   - **What it demonstrates:** Engine status **`AMBIGUOUS`** returning two concrete interpretations (Graduated = $25.00, Volume = $20.00; difference = 0 cents). AI generates finding type `CONTRACT_AMBIGUITY`, credit approval is blocked, and uploading a contract amendment (`POST /api/cases/{id}/evidence/rules`) supersedes the conflicting rule and resolves ambiguity.
3. **`case-delta-103` — Clean Invoice Verification (No Discrepancy)**
   - **Contract Rule:** `FLAT` at 10000 cents ($100.00).
   - **Billed Amount:** $100.00 (10000 cents).
   - **Usage Telemetry:** None required.
   - **What it demonstrates:** Engine status **`OK`** with zero difference cents. Proves clean reconciliation where no credit is eligible.

---

## 🚶 Step-by-Step Reviewer Walkthrough

Follow this end-to-end journey in the UI to evaluate the complete dispute governance lifecycle:

1. **Select or Open Case:**
   - In the Disputes table, click on **`case-acme-101`**.
2. **Execute Deterministic Calculation:**
   - Under the **Deterministic Engine** tab, review the pre-computed run or click **"Execute Deterministic Calculation"**.
   - Observe line item reconciliation: 250 billable units @ 10c = $25.00; 150 staging units marked exempt ($0.00); billed $50.00 $\rightarrow$ discrepancy of **-$25.00 (Overcharge)**.
3. **Trigger Autonomous Investigation:**
   - Switch to the **AI Investigation** tab and click **"Trigger Investigation Run"**.
   - The LangGraph workflow executes. Review the generated finding anchored to `line-acme-api` with engine-derived type `CONFIRMED_CALCULATION_DISCREPANCY` and resolution options.
4. **Human Review Finding:**
   - Click **"Review Finding"** $\rightarrow$ select **`ACCEPT`** $\rightarrow$ enter a justification note $\rightarrow$ click **"Submit Review"**.
   - Notice the status badge updates to **Accepted**, enabling credit approval.
5. **Inspect Credit Cap & Approve Credit:**
   - Switch to the **Credit Issuance** tab.
   - Notice the backend cap endpoint displays: Eligible: $25.00, Prior Adjustments: $5.00, **Remaining Cap: $20.00**.
   - Select the accepted finding and click **"Approve & Issue Credit"**.
   - The credit row appears in the table with `invoice_line_id: line-acme-api`. Remaining Cap immediately drops to **$0.00**, and the approve button disables with reason *"Credit cap exhausted ($0.00 remaining)"*.
   - Attempting duplicate submission displays the toast: *"Credit already approved for this finding"*.
6. **Upload Contract Amendment & Observe Invalidation:**
   - Open **"Upload Evidence"** $\rightarrow$ select the **"Contract / Adjustment"** tab.
   - Add an amendment rule or adjustment.
   - Upon upload, notice: Case evidence version bumps (v1 $\rightarrow$ v2), prior findings and options are flagged **STALE** with visible stale reasons, and the UI prompts for re-investigation.

---

## 🛠️ Core Features & Engineering Implementation

### 1. Pure Deterministic Billing Engine
- Implemented in [`backend/app/billing_engine.py`](backend/app/billing_engine.py).
- Supported rules: `FLAT`, `PER_UNIT`, `TIERED_GRADUATED`, `TIERED_VOLUME`, `INCLUDED_UNITS`, `DISCOUNT_PCT`, `MINIMUM_COMMIT`.
- Billing period enforcement: Events outside `[period_start, period_end]` are quarantined with reason `"Outside billing period"`.
- Cryptographic anchors: Emits an immutable `result_id` (`res_` + SHA-256) per line item.

### 2. Multi-Provider LLM Resilience
- Implemented in [`backend/app/agent/providers.py`](backend/app/agent/providers.py) and [`llm_client.py`](backend/app/agent/llm_client.py).
- Fallback chain: **Gemini (primary) $\rightarrow$ Groq $\rightarrow$ OpenRouter**.
- Automatic retry on 429/5xx/timeout; immediate failover on 401/403/404.
- Verify live connectivity anytime with:
  ```bash
  python backend/scripts/check_llm.py
  ```

### 3. Concurrency-Safe Credit Approval
- Implemented in [`backend/app/services/credit_service.py`](backend/app/services/credit_service.py).
- Row-level lock: `SELECT FOR UPDATE` on PostgreSQL; `BEGIN IMMEDIATE` on SQLite.
- Shared cap computation: `compute_remaining_cap` verifies line and case-wide adjustments.
- Idempotency key: `SHA-256(case_id:invoice_line_id:finding_id)` strictly blocks repeat credits with HTTP 409.

### 4. Append-Only Audit Logging & Storage Triggers
- Physical SQLite triggers (`RAISE(ABORT)`) and PostgreSQL triggers block application-level `UPDATE` and `DELETE` queries on `case_events`, `calculation_line_results`, `credits`, `finding_reviews`, and `evidence_versions`.

---

## ⚖️ Scope: Completed vs Excluded

### Completed Scope
- [x] Pure deterministic calculation engine with Decimal math and boundary rounding.
- [x] LangGraph multi-node autonomous investigation with multi-provider fallback.
- [x] Per-line finding generation and independent resolution options.
- [x] Deterministic engine-derived finding types replacing contradictory AI text.
- [x] Repeat-run atomic guard via database partial unique index with 180s TTL reaper.
- [x] Contract rule amendments with superseding (`is_active=False`) and content hashing.
- [x] Billing period usage filtering (`period_start`, `period_end`).
- [x] Accessible dark-mode React UI with separate non-flickering refresh states.

### Excluded Scope
- **Tax Calculation:** VAT, sales taxes, and jurisdiction exemptions are excluded.
- **Payment Gateway Rails:** Mock credit entries are generated; direct Stripe/banking integration is excluded.
- **Unstructured OCR:** Ingestion uses structured JSON API payloads and presets; OCR extraction is excluded.
- **External Accounting Sync:** ERP synchronization (e.g. NetSuite/QuickBooks) is excluded.

---

## ⚠️ Known Limitations

1. **Privileged DB Users**: Triggers protect against application-level modifications; database administrators with direct DDL access can disable triggers.
2. **SQLite vs PostgreSQL Concurrency**: Concurrency row-locking is fully backed by `SELECT FOR UPDATE` in PostgreSQL; SQLite relies on `BEGIN IMMEDIATE`.
3. **Single Discount Rule**: One percentage discount is supported per line; multiple discounts yield `AMBIGUOUS`.

---

## 🔌 API Route Reference

| Method | Endpoint | Description | Status |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/cases` | Create a dispute case with lines and rules | **201 Created** |
| `GET` | `/api/cases` | List all dispute cases | **200 OK** |
| `GET` | `/api/cases/{id}` | Get case metadata, lines, and active rules | **200 OK** |
| `POST` | `/api/cases/{id}/transition` | Transition status (`OPEN`, `AWAITING_INFO`, `RESOLVED`, `REOPENED`) | **200 OK / 409** |
| `GET` | `/api/cases/{id}/events` | Read append-only audit trail | **200 OK** |
| `POST` | `/api/cases/{id}/evidence` | Upload usage telemetry events (bumps version) | **200 OK / 409 / 422** |
| `POST` | `/api/cases/{id}/evidence/rules` | Upload contract rules/amendments with superseding | **200 OK** |
| `POST` | `/api/calculations/run` | Execute deterministic billing calculation | **200 OK** |
| `GET` | `/api/calculations/case/{case_id}`| Retrieve all calculation runs for a case | **200 OK** |
| `POST` | `/api/cases/{case_id}/investigations` | Run autonomous investigation (502 on failure, 503 if unconfigured) | **201 / 502 / 503** |
| `GET` | `/api/cases/{case_id}/investigations` | List investigation runs for a case | **200 OK** |
| `GET` | `/api/findings/case/{case_id}` | List structured findings and review history | **200 OK** |
| `POST` | `/api/findings/{id}/review` | Submit human review (`ACCEPT`, `EDIT`, `REJECT`) | **200 OK** |
| `GET` | `/api/credits/case/{case_id}/cap` | Read calculated credit cap and adjustments | **200 OK** |
| `POST` | `/api/credits/approve` | Approve financial credit under lock and cap | **201 / 400 / 409** |
| `GET` | `/api/credits/case/{case_id}` | List approved credits for a case | **200 OK** |
| `GET` | `/api/llm/status` | List LLM provider configuration status | **200 OK** |
| `GET` | `/healthz` | System health probe | **200 OK** |

---

## ☁️ Deployment & Database Migrations

- **Platform Blueprint:** Documented in [`render.yaml`](render.yaml) for Node 20 and Python 3.12.
- **Alembic vs create_all:**
  - `create_all_tables()` automatically initializes all 14 tables and append-only database triggers for fast local testing and greenfield SQLite setups.
  - Alembic migrations (`alembic upgrade head`) manage sequential DDL evolutions (partial indexes, active flags, billing periods) in production and PostgreSQL environments.
- **Multi-User Reviewer Tokens (`REVIEWER_TOKENS`):**
  - Set `REVIEWER_TOKENS="token_alice:alice@domain.com,token_bob:bob@domain.com"` in `.env` to map specific bearer tokens to individual reviewer identities in the audit log.

---

## 🧪 Automated Test Suite (143 Passed, 1 Skipped)

Run the backend test suite:
```bash
cd backend && LLM_MODE=mock pytest -q
```
**Actual pytest output:**
```
================== 143 passed, 1 skipped, 1 warning in 9.43s ==================
```

### Per-File Test Function Count (`grep -c "def test_"`)
| Test File | Count | Focus Area |
| :--- | :--- | :--- |
| `tests/test_billing_engine.py` | 67 | Pure deterministic math, slabs, rounding, commitments, exemptions |
| `tests/test_agent.py` | 24 | LangGraph pipeline, citations, per-line findings, injection defense, TTL |
| `tests/test_api_and_services.py`| 23 | CRUD, transitions, calculation API, reviews, credits, audit |
| `tests/test_models_and_db.py` | 10 | Schema constraints, append-only triggers, unique constraints |
| `tests/test_llm_resilience.py` | 10 | Provider fallback, 429 quota retries, fail-loud 502, secret hygiene |
| `tests/test_task9.py` | 4 | Billing period quarantine, 503 provider check, review ordering |
| `tests/test_credit_cap.py` | 3 | Credit cap endpoint, adjustment deductions, duplicate 409 |
| `tests/test_seed.py` | 2 | Auto-seed idempotency, scenario verification, failure logging |
| `tests/test_concurrency.py` | 2 | 10-thread concurrent credit approval stress test (1 skipped on SQLite) |
| **Total Test Functions** | **145** | *(Pytest collected: 144 test items — 143 passed, 1 skipped)* |

---

## 🚀 Local Setup & Verification

### 1. Configure Environment
```bash
cp .env.example .env
```
Edit `.env` to configure your database URL and optional LLM keys.

### 2. Backend Setup
```bash
cd backend
python -m venv .venv

# Activate:
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
alembic upgrade head
python scripts/check_llm.py
```

### 3. Run Backend Tests
```bash
$env:LLM_MODE="mock"; pytest -q
```

### 4. Frontend Setup & Verification
```bash
cd ../frontend
npm ci
npm run lint
npm run build
npm run dev
```
Visit `http://localhost:5173` to access the FairBill workspace.
