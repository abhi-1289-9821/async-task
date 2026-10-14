# FairBill — Autonomous Billing Dispute Investigation & Governance

FairBill is a full-stack, AI-assisted platform engineered to investigate, recalculate, and resolve SaaS and cloud billing disputes. The system pairs a **pure deterministic pricing engine** (Python `Decimal`, integer cents) for all financial mathematics with an **autonomous LangGraph multi-node investigation workflow**, human-in-the-loop review, concurrency-safe credit issuance, and an immutable append-only audit trail.

---

## Reviewer Access & Quick Start

> **Production Credentials**: When `ENVIRONMENT=production`, reviewer and viewer tokens are configured via `DEMO_REVIEWER_TOKEN` and `DEMO_VIEWER_TOKEN` environment variables and provided in the submission remarks. Default fallback tokens are strictly blocked in production.

- **Deployed Live URL:** `https://fairbill-audit.onrender.com` *(or local: `http://localhost:5173`)*
- **Reviewer Token:** Set via `DEMO_REVIEWER_TOKEN` (provided in submission remarks)
- **Viewer Token:** Set via `DEMO_VIEWER_TOKEN` (provided in submission remarks)

### Quick Start
1. Open the application at `https://fairbill-audit.onrender.com` (or local `http://localhost:5173`).
2. Click the **Token** button in the navigation bar and enter your reviewer token (or open `https://fairbill-audit.onrender.com/?token=<YOUR_TOKEN>`).
3. Open **`case-acme-101`** to inspect the deterministic calculation, trigger the investigation agent, and review findings.

---

## Architecture

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
│  (backend/app/billing_engine.py)│       │     (LangGraph Multi-Node)      │       │  (backend/app/credit_service.py)│
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
                                  │  - SQLAlchemy ORM Data Layer            │
                                  │  - Partial Unique Index on RUNNING runs │
                                  │  - Append-only DDL triggers             │
                                  │  - Alembic migrations & create_all      │
                                  └─────────────────────────────────────────┘
```

### Architectural Invariants
1. **Deterministic Financial Math Only**: Money is computed strictly in Python using standard library `Decimal`, integer cents ($10.00 = 1000$ cents), and `ROUND_HALF_UP` boundary rounding in [`backend/app/billing_engine.py`](backend/app/billing_engine.py). **The LLM never computes, invents, or changes financial figures.**
2. **AI Reasoner & Narrator**: LangGraph and LLM providers formulate structured findings, explanation hypotheses, and proposed resolutions, citing immutable cryptographic result IDs (`result_id`).
3. **Fail-Loud Guarantee**: When `LLM_MODE=real`, the system never fakes or fabricates AI findings. If upstream providers fail or timeout, the run transitions to `FAILED`, appends an `INVESTIGATION_RUN_FAILED` audit event, and returns **HTTP 502 Bad Gateway**. If no LLM provider is configured, it returns **HTTP 503 Service Unavailable**.
4. **Zero Bundle Secrets**: Client tokens are strictly user-supplied or loaded from session/local storage. No demo tokens or API keys exist in client build bundles.

---

## Local Setup

### 1. Environment Configuration

#### PowerShell (Windows)
```powershell
Copy-Item .env.example .env
```

#### Bash (Linux/macOS)
```bash
cp .env.example .env
```

Edit `.env` to configure your database URL and optional LLM provider keys.

### 2. Backend Setup

#### PowerShell (Windows)
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
alembic upgrade head
python scripts\check_llm.py
uvicorn app.main:app --reload --port 8000
```

#### Bash (Linux/macOS)
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
python scripts/check_llm.py
uvicorn app.main:app --reload --port 8000
```

### 3. Frontend Setup

#### PowerShell (Windows)
```powershell
cd frontend
npm ci
npm run dev
```

#### Bash (Linux/macOS)
```bash
cd frontend
npm ci
npm run dev
```

Visit `http://localhost:5173` to access the FairBill interface.

---

## Automated Test Suite

Run pytest to see current results across all test suites.

### Backend Tests

#### PowerShell (Windows)
```powershell
cd backend
$env:LLM_MODE="mock"; pytest -q
```

#### Bash (Linux/macOS)
```bash
cd backend
LLM_MODE=mock pytest -q
```

*(Run pytest to see current results — all test files execute in mock mode with zero external network dependency).*

### Per-File Test Suite Overview
| Test File | Focus Area |
| :--- | :--- |
| `tests/test_billing_engine.py` | Pure deterministic math, slabs, rounding, commitments, exemptions, undisputed overcharge |
| `tests/test_agent.py` | LangGraph pipeline, citations, per-line findings, injection defense, TTL reaper |
| `tests/test_api_and_services.py` | CRUD, transitions, calculation API, reviews, credits, audit trail |
| `tests/test_models_and_db.py` | Schema constraints, append-only triggers, composite keys |
| `tests/test_llm_resilience.py` | Provider fallback, 429 quota retries, fail-loud 502, calculation persistence |
| `tests/test_billing_period_and_provider_checks.py` | Billing period quarantine, 503 provider check, review ordering |
| `tests/test_credit_cap.py` | Credit cap endpoint, adjustment deductions, cross-case line isolation, duplicate 409 |
| `tests/test_generalized_disputes.py` | Cross-case multi-customer regression tests (EUR currency, multi-line invoices, graduated vs volume boundaries, prompt injection resistance, evidence version invalidation, idempotency, quarantine) |
| `tests/test_seed.py` | Auto-seed idempotency, scenario verification, failure logging |
| `tests/test_concurrency.py` | 10-thread concurrent credit approval stress test (Postgres locking) |

**Backend Test Results:** 172 passed, 1 skipped (Postgres concurrency test gracefully skipped on local SQLite), 0 failures in 14.87s.

### Frontend Quality Gates

#### PowerShell & Bash
```bash
cd frontend
npm run lint    # oxlint: 0 warnings, 0 errors in 77ms
npm test        # Vitest + React Testing Library (15 tests across 2 suites, all passing in 2.75s)
npm run build   # Production bundle verification (built in 596ms, 0 errors)
```

---

## Scope: Completed vs Excluded

### Completed Scope
- **Generalized Pricing Engine:** Pure deterministic calculation engine with Python `Decimal`, integer cents, supporting all 7 pricing rule types (`FLAT`, `PER_UNIT`, `TIERED_GRADUATED`, `TIERED_VOLUME`, `INCLUDED_UNITS`, `DISCOUNT_PCT`, `MINIMUM_COMMIT`) without customer-specific logic.
- **Dynamic Pricing Forms:** React forms (`CreateCaseModal.jsx`, `EvidenceModal.jsx`, `LinesTab.jsx`) dynamically render and validate fields, repeatable tier slabs (with add/remove and gap/overlap validation), included units, overage rates, discounts, minimum commitments, and environment exemptions for any customer or invoice.
- **Generic Contract Ambiguity & Scenarios:** Evaluates any set of competing primary rules, generates discrete alternative scenarios, labels them as scenarios (not confirmed amounts), and computes the undisputed overcharge (`billed - max(scenarios)`).
- **Strict Evidence & Finding Lifecycle:** Evidence changes bump the case evidence version, invalidate prior calculations and resolution options, mark older findings as stale, and strictly block credit approvals on outdated evidence versions.
- **Prompt Injection & Untrusted Input Isolation:** Customer statements and descriptions are isolated inside escaped `<untrusted_...>` XML delimiters. System instructions mandate that LLM never executes customer directives or invents financial figures.
- **Multi-Line & Multi-Currency Support:** Recalculates multi-line invoices and aggregates line-level reconciliation without assuming fixed line counts or currencies.
- **Autonomous Multi-Provider Investigation:** Multi-node LangGraph workflow with fallback across Gemini, Groq, and OpenRouter, enforcing deterministic engine-derived finding types and valid citation anchors (`res_...`, `line-...`, `rule-...`, `ev-...`).
- **Concurrency-Safe Credit Governance:** Row-level locks, cumulative remaining cap enforcement, single-credit-per-finding constraints, and unique idempotency keys returning HTTP 409 Conflict on duplicate approval attempts.
- **Append-Only Audit Logging:** Physical database triggers on both SQLite and PostgreSQL protecting case events, calculation line results, reviews, and credits from deletion or tampering.

### Excluded Scope
- **Tax Calculation:** VAT, sales taxes, and jurisdiction exemptions are excluded.
- **Payment Gateway Rails:** Mock credit entries are generated; direct Stripe/banking integration is excluded.
- **Unstructured OCR:** Ingestion uses structured JSON API payloads and presets; OCR extraction is excluded.
- **External Accounting Sync:** ERP synchronization (e.g. NetSuite/QuickBooks) is excluded.

---

## Known Limitations

1. **Production Database Persistence**: Production deployments on Render **must use a hosted PostgreSQL `DATABASE_URL`** (such as [Neon](https://neon.tech)), because the default SQLite filesystem on Render is ephemeral and resets across service redeployments and restarts.
2. **Privileged DB Users**: Append-only database triggers protect against application-level modifications; database administrators with direct superuser DDL access can disable triggers.
3. **SQLite vs PostgreSQL Concurrency**: Concurrency row-locking is fully backed by `SELECT FOR UPDATE` in PostgreSQL; SQLite relies on `BEGIN IMMEDIATE` table-level transactions.
4. **Single Discount Rule**: One percentage discount is supported per line; multiple competing discounts yield `AMBIGUOUS`.

---

## Auto-Seeded Demonstration Cases

On startup against an empty database, `backend/app/seed.py` idempotently seeds 12 comprehensive dispute scenarios (the 7 benchmark dispute scenarios + 5 foundational regression scenarios):

### Benchmark Dispute Scenarios
1. **`case-acme-a-1042` — Acme A: Missing Evidence, Unverified Usage & Claimed Prior Credit**
   - **Contract Rule:** `PER_UNIT` at 12 cents/unit; `exempt_environments: ["staging", "development"]`.
   - **Billed Amount:** $180.00 (1,500 units billed).
   - **Dispute:** Customer asserts 1,200 units and demands a $20 support credit promise.
   - **Usage Telemetry:** None verified in system.
   - **What it demonstrates:** Engine status **`INSUFFICIENT_DATA`**. The system strictly refuses to calculate money or approve credits from customer claims alone without verified telemetry.
2. **`case-beta-b-2091` — Beta B: Graduated Tier Boundary Step Precision**
   - **Contract Rule:** `TIERED_GRADUATED` (0-1,000 @ 20c; 1,001-5,000 @ 15c; 5,001+ @ 10c).
   - **Billed Amount:** $900.00 (90,000 cents).
   - **Usage Telemetry:** Exactly 5,000 verified production units.
   - **What it demonstrates:** Exact slab boundary precision. Correct calculation is $200.00 (first 1,000) + $600.00 (next 4,000) = $800.00. Result: **$100.00 confirmed overcharge**.
3. **`case-bravo-c-3105` — Bravo C: Contractual Ambiguity with Undisputed Partial Recovery**
   - **Contract Rule:** Competing `TIERED_GRADUATED` ($25.00) vs `TIERED_VOLUME` ($20.00) rules on the same line.
   - **Billed Amount:** $40.00 (4,000 cents).
   - **Usage Telemetry:** 200 production units.
   - **What it demonstrates:** Engine status **`AMBIGUOUS`**. Both valid contractual interpretations are computed and stored. The deterministic engine calculates the undisputed minimum overcharge ($40 - $25 = **$15.00**), enabling immediate partial credit while the remainder awaits contractual amendment.
4. **`case-gamma-d-4401` — Gamma D: Credit Cap Enforcement with Prior Courtesy Adjustment**
   - **Contract Rule:** `PER_UNIT` at 10 cents/unit.
   - **Billed Amount:** $80.00 (8,000 cents).
   - **Usage Telemetry:** 500 verified production units ($50.00 recalculated).
   - **Prior Adjustment:** $5.00 (500 cents) prior courtesy credit.
   - **What it demonstrates:** Gross overcharge is $30.00. Cap endpoint and credit service enforce cumulative cap deduction ($30.00 - $5.00 = **$25.00 remaining cap**).
5. **`case-delta-e-5510` — Delta E: Clean Invoice Verification (No Discrepancy)**
   - **Contract Rule:** `FLAT` at 10,000 cents ($100.00).
   - **Billed Amount:** $100.00 (10,000 cents).
   - **What it demonstrates:** Engine status **`OK`** with zero difference cents. Proves clean reconciliation where no credit is eligible.
6. **`case-epsilon-f-6620` — Epsilon F: Minimum Spend Commitment Enforcement**
   - **Contract Rule:** `MINIMUM_COMMIT` of $500.00 with $0.10/unit overage.
   - **Billed Amount:** $600.00.
   - **Usage Telemetry:** 3,000 units ($300.00 metered).
   - **What it demonstrates:** Engine enforces minimum commitment floor ($500.00), yielding a $100.00 overcharge.
7. **`case-zeta-g-7730` — Zeta G: Percentage Discount on Eligible Service Lines**
   - **Contract Rule:** 15% `DISCOUNT_PCT` on eligible compute lines, excluding separate support fees.
   - **Billed Amount:** Full non-discounted eligible subtotal.
   - **What it demonstrates:** Accurate percentage discount application order without contaminating excluded service items.

### Foundational Regression Cases
8. **`case-acme-101`**: Staging environment exemption and prior goodwill adjustment deduction.
9. **`case-bravo-102`**: Dual-clause tier ambiguity with discrete scenario modeling.
10. **`case-delta-103`**: Flat rate clean invoice verification.
11. **`case-krypton-ver-01`**: Evidence version bump and stale finding invalidation lifecycle test.
12. **`case-titan-cap-01`**: Concurrency-safe credit cap deduction test.

---

## Step-by-Step Reviewer Walkthrough

Follow this end-to-end journey in the UI to evaluate the complete dispute governance lifecycle:

1. **Select or Open Case:**
   - In the Disputes table, click on **`case-acme-101`**.
2. **Execute Deterministic Calculation:**
   - Under the **Deterministic Engine** tab, review the pre-computed run or click **"Run Billing Engine"**.
   - Observe line item reconciliation: 250 billable units @ 10c = $25.00; 150 staging units marked exempt ($0.00); billed $50.00 $\rightarrow$ discrepancy of **-$25.00 (Overcharge)**.
3. **Trigger LangGraph Investigation:**
   - Switch to the **AI Investigation (LangGraph)** tab $\rightarrow$ click **"Trigger Investigation Run"**.
   - The multi-node agent analyzes evidence, synthesizes a finding with verified citation anchors (`res_...`, `line-...`), and proposes resolution options.
4. **Human Review:**
   - Click **"Human Review"** on the generated finding.
   - Select **ACCEPT** (or EDIT) and provide a reviewer justification note. Submit the review.
5. **Concurrency-Safe Credit Issuance:**
   - Switch to the **Credit Issuance** tab.
   - Observe the live cap breakdown: Calculated Overcharge ($25.00) minus Prior Line Adjustments ($5.00) = Remaining Line Cap of **$20.00**.
   - Select the accepted finding and click **"Approve Credit Under Row Lock"**.
   - The credit row appears in the table with `invoice_line_id: line-acme-api`. Remaining Cap immediately drops to **$0.00**, and the approve button disables with reason *"Remaining allowable credit cap is $0.00"*.
   - Attempting duplicate credit approval for the same finding returns HTTP 409 and displays: *"Credit already approved for this finding"*.
6. **Upload Contract Amendment & Observe Invalidation:**
   - Click **"Upload Evidence"** $\rightarrow$ select the **"Contract / Adjustment"** tab.
   - Add an amendment rule or adjustment.
   - Upon upload, notice: Case evidence version bumps (v1 $\rightarrow$ v2), prior findings and options are flagged **STALE**, and the UI prompts for re-investigation.

---

## API Route Reference

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
| `POST` | `/api/findings/{id}/review` | Submit human review (`ACCEPT`, `EDIT`, `REJECT`) | **200 OK / 409** |
| `GET` | `/api/credits/case/{case_id}/cap` | Read calculated credit cap and adjustments | **200 OK** |
| `POST` | `/api/credits/approve` | Approve financial credit under lock and cap | **201 / 400 / 409** |
| `GET` | `/api/credits/case/{case_id}` | List approved credits for a case | **200 OK** |
| `GET` | `/api/llm/status` | List LLM provider configuration status | **200 OK** |
| `GET` | `/healthz` | System health probe | **200 OK** |

---

## Deployment & Database Migrations

- **Platform Blueprint:** Documented in [`render.yaml`](render.yaml) for Node 20 and Python 3.12 with automated `alembic upgrade head` pre-deploy and startup migration execution.
- **Production Database Requirement:** Production deployments on Render **must use a hosted PostgreSQL `DATABASE_URL`** (such as [Neon](https://neon.tech)), because the default SQLite filesystem on Render is ephemeral and resets across service redeployments and restarts.
- **Alembic vs create_all:**
  - `create_all_tables()` automatically initializes all tables and append-only database triggers for fast local testing and greenfield SQLite setups.
  - Alembic migrations (`alembic upgrade head`) manage sequential DDL evolutions in production and PostgreSQL environments.
  - Database seeding (`seed_demo_cases_if_empty`) runs safely and idempotently after migrations on startup, only inserting demo scenarios if the database contains 0 cases.
- **Multi-User Reviewer Tokens (`REVIEWER_TOKENS`):**
  - Set `REVIEWER_TOKENS="token_alice:alice@domain.com,token_bob:bob@domain.com"` in `.env` to map specific bearer tokens to individual reviewer identities in the audit log.
