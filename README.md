# FairBill — Autonomous Billing Dispute Investigation & Governance

FairBill is a full-stack, AI-assisted platform engineered to investigate, recalculate, and resolve SaaS and cloud billing disputes. The system pairs a **pure deterministic pricing engine** (Python `Decimal`, integer cents) for all financial mathematics with an **autonomous LangGraph multi-node investigation workflow**, human-in-the-loop review, concurrency-safe credit issuance, and an immutable append-only audit trail.

---

## Reviewer Access & Quick Start

> **Live Evaluation Credentials**: The live deployment is deliberately configured in **Evaluation Demo Mode** (`DEMO_MODE=true` / `VITE_DEMO_MODE=true`) so visitors and automated evaluator suites are automatically authenticated as Reviewer by default without requiring manual credential entry.
>
> - **Primary Deployed Full-Stack URL (Render + Neon PostgreSQL):** **`https://fairbill-hrrg.onrender.com`**
> - **Backup / Mirror URL (Vercel):** `https://fairbill-1289.vercel.app`
> - **Database:** Hosted **Neon PostgreSQL** (`postgresql+psycopg2://...`), providing durable storage for cases, evidence versions, and append-only audit trails.
> - **Reviewer Token:** `demo-reviewer-token-2026` (Full access: recalculate, trigger AI investigations, review findings, approve credits)
> - **Viewer Token:** `demo-viewer-token-2026` (Read-only access: view cases, calculations, evidence, audit log)
>
> ⚠️ **Render Free-Tier Cold Starts**: On Render's free tier, instances spin down after 15 minutes of inactivity. When accessed after being idle, Render displays a temporary "Service waking up / Application loading" initialization screen for **~45 seconds** while compute resources are allocated. Once warmed up, all requests respond with normal sub-second latencies. (Pinging `/healthz` on a scheduled interval keeps the instance permanently warm).

### Quick Start
1. Open the application directly at **`https://fairbill-hrrg.onrender.com`** (authenticated automatically, or pass `?token=demo-reviewer-token-2026`).
2. Explore any of the **12 real-world dispute cases** (e.g., `case-1-acme-a` through `case-7-golf`, `case-acme-unverified`, `case-acme-101`, `case-bravo-102`).
3. Click **Run Billing Engine** to test the pure deterministic Python calculation engine, or **Trigger AI Investigation** to run the multi-node LangGraph pipeline.
4. Review findings, inspect evidence citations, and approve concurrency-safe credits under row-level locks and cumulative caps.

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
│  (backend/app/billing_engine.py)│       │     (LangGraph Multi-Node)      │       │(backend/app/services/credit_service.py)│
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
4. **Auth & DEMO_MODE Security**: Constant-time token comparison via `secrets.compare_digest`. When `DEMO_MODE=false` in production, default demo evaluation tokens are refused at startup and during request authentication. In production builds, frontend `getToken()` returns empty unless `VITE_DEMO_MODE=true` was explicitly passed at build time.
5. **Backend Single Source of Truth for Money**: Backend `credit_service.compute_remaining_cap` is the authoritative source for remaining caps, eligible overcharges, and adjustments across all screens. Frontend never calculates or recomputes recovery caps.
6. **Zero Hardcoded Currency**: Centralized `formatMoney(cents, currency)` using `Intl.NumberFormat` formats all user-visible money values according to the dispute case currency (`EUR`, `GBP`, `USD`).
7. **Grounded AI Quality Gates**: Finding validation rejects ungrounded hypotheses attributing rates or mechanisms not present in evidence, validates missing evidence questions, and renders a visible "Template analysis, not AI" banner if fallback mock generation is ever engaged.

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

All tests execute with a plain `pytest` command—no manual environment variables required (`backend/tests/conftest.py` guarantees test isolation and sets `LLM_MODE=mock` automatically).

### Backend Tests
```bash
pytest
```
*(Executes all 15 test suites in 20s with zero external network dependencies).*

### Per-File Test Suite Overview
| Test File | Focus Area |
| :--- | :--- |
| `tests/test_golden_case_and_ledger.py` | Reference Golden Case (EUR), single-source ledger lifecycle, verified vs unverified adjustment deduplication |
| `tests/test_anti_regression_matrix.py` | Hypothesis property tests asserting 7 invariants across USD/EUR/GBP, 7 rule types, multi-line, adjustments, and period scenarios |
| `tests/test_ai_quality_gates.py` | Grounded root-cause hypotheses, missing evidence question validation, currency formatting, and written-out numbers |
| `tests/test_period_telemetry.py` | Telemetry timestamps across past/current/future billing periods and quarantine reason inspection |
| `tests/test_api_smoke.py` | End-to-end clean database migration and API lifecycle smoke test |
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

**Backend Test Results:** 233 passed, 1 skipped (Postgres concurrency test gracefully skipped on local SQLite), 0 failures in 21.77s.

### Frontend Quality Gates & Guards
```bash
npm run lint && npm run test && npm run build
```
- **Static & Runtime Currency Guard (`currency_guard.test.jsx`):** Scans all `frontend/src` source code for hardcoded `\$\$\{`, `toFixed(2)` outside `formatMoney`, and literal `($ USD)`. Asserts EUR (`€`) and GBP (`£`) symbol rendering across Engine, Investigation, and Credits tabs.
- **Single Source of Truth Verification:** Asserts that Engine, Investigation, and Credits tabs display the identical allowable recovery cap value from the backend ledger fixture.
- **Frontend Test Results:** 23 passed (3 test files: `currency_guard.test.jsx`, `components.test.jsx`, `review_and_evidence.test.jsx`), 0 errors in 4.03s.

**Combined Automated Test Count:** 256 passing tests (233 backend + 23 frontend).

#### PowerShell & Bash
```bash
cd frontend
npm run lint    # oxlint: 0 warnings, 0 errors in 119ms
npm test        # Vitest + React Testing Library (23 tests across 3 test files, all passing in 4.03s)
npm run build   # Production bundle verification (built in 549ms, 0 errors)
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
1. **`case-1-acme-a` — Acme A: Missing Evidence, Unverified Usage & Claimed Prior Credit**
   - **Contract Rule:** `PER_UNIT` at 12 cents/unit; `exempt_environments: ["staging", "development"]`.
   - **Billed Amount:** $180.00 (1,500 units billed).
   - **Dispute:** Customer asserts 1,200 units and demands a $20 support credit promise.
   - **Usage Telemetry:** None verified in system.
   - **What it demonstrates:** Engine status **`INSUFFICIENT_DATA`**. The system strictly refuses to calculate money or approve credits from customer claims alone without verified telemetry.
2. **`case-2-acme-b` — Acme B: Verified Graduated-Tier Overcharge**
   - **Contract Rule:** `TIERED_GRADUATED` (0-500 @ 80c; 501-1,000 @ 45c; 1,001+ @ 25c).
   - **Billed Amount:** $950.00 (95,000 cents).
   - **Usage Telemetry:** Exactly 1,200 verified production units ($675.00 recalculated).
   - **What it demonstrates:** Exact graduated slab step calculation ($400 + $225 + $50 = $675.00), yielding a confirmed **$275.00 overcharge discrepancy**.
3. **`case-3-bravo` — Bravo: Conflicting Contract Amendments at Tier Threshold**
   - **Contract Rule:** Competing `TIERED_GRADUATED` vs `TIERED_VOLUME` amendments at volume threshold.
   - **Billed Amount:** $400.00 (40,000 cents).
   - **Usage Telemetry:** 200 production units.
   - **What it demonstrates:** Engine status **`AMBIGUOUS`**. Both valid contractual interpretations are computed and stored. The deterministic engine calculates the undisputed minimum overcharge, enabling immediate partial credit while the remainder awaits contractual amendment.
4. **`case-4-delta` — Delta: Fixed Fee, Duplicate Charge, Prior Credit Accounting**
   - **Contract Rule:** `FLAT` service fee with duplicate billing and prior courtesy adjustment.
   - **Billed Amount:** $250.00 (25,000 cents).
   - **What it demonstrates:** Single source of truth cap enforcement subtracting verified adjustments from the gross overcharge.
5. **`case-5-echo` — Echo: Included Units Allowance & Exempt Environment Removal**
   - **Contract Rule:** `INCLUDED_UNITS` with environment exemption filtering.
   - **What it demonstrates:** Clean isolation of staging/dev usage and calculation of billable overage units only above the included allowance.
6. **`case-6-foxtrot` — Foxtrot: Percentage Discount on Eligible Base & Prompt Injection Resilience**
   - **Contract Rule:** 15% `DISCOUNT_PCT` on eligible compute lines with an untrusted customer prompt injection attack embedded in dispute text.
   - **What it demonstrates:** Percentage discount applied accurately; system ignores adversarial prompts attempting to dictate refund amounts.
7. **`case-7-golf` — Golf: Minimum Commitment Floor & Alleged Waiver**
   - **Contract Rule:** `MINIMUM_COMMIT` of $500.00 with metered usage below commit.
   - **What it demonstrates:** Engine enforces minimum commitment floor ($500.00) despite customer claims of verbal waivers.

### Foundational Regression Cases
8. **`case-acme-unverified`**: Pure unverified customer usage claim asserting support promises.
9. **`case-acme-verified`**: Verified usage telemetry with verified credit adjustment ledger accounting.
10. **`case-acme-101`**: Staging environment exemption and prior goodwill adjustment deduction.
11. **`case-bravo-102`**: Dual-clause tier ambiguity with discrete scenario modeling.
12. **`case-delta-103`**: Flat rate clean invoice verification.

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
| `POST` | `/api/findings/{id}/review` | Submit human review (`ACCEPT`, `EDIT`, `REJECT`) | **201 Created / 409** |
| `GET` | `/api/credits/case/{case_id}/cap` | Read calculated credit cap and adjustments | **200 OK** |
| `POST` | `/api/credits/approve` | Approve financial credit under lock and cap | **201 / 400 / 409** |
| `GET` | `/api/credits/case/{case_id}` | List approved credits for a case | **200 OK** |
| `GET` | `/api/llm/status` | List LLM provider configuration status | **200 OK** |
| `GET` | `/healthz` | System health probe | **200 OK** |

---

## Observability & Structured Logging

The platform incorporates comprehensive end-to-end structured JSON logging for auditing, debugging, and AI transparency:
- **Request ID Tracking & Correlation (`request_id_ctx`):** Handled via `StructuredLoggingMiddleware` in `backend/app/logging.py`. Every inbound HTTP request is assigned a unique `X-Request-ID` (or adopts incoming headers) propagated through Python `ContextVar`, tagging all downstream logs, database transactions, and agent traces.
- **LLM Execution Observability (`log_llm_execution`):** Emits structured audit events recording provider name (`gemini`, `groq`, `openrouter`), model string, attempt index, latency in milliseconds, token counts (prompt, completion, total), and success/failure status. Secrets and API keys are strictly redacted via `sanitize_error_message`.
- **Agent Workflow Node Telemetry (`log_agent_node_execution`):** Records latency, node transitions (`gather_evidence` $\rightarrow$ `run_calculation` $\rightarrow$ `analyze_findings` $\rightarrow$ `formulate_options` $\rightarrow$ `validate_and_sanitize`), and state payload metadata.

---

## Environment Configuration (`.env.example`)

A clean template is provided at [`.env.example`](.env.example):
- `ENVIRONMENT`: Set to `production` or `development`.
- `DATABASE_URL`: Hosted PostgreSQL connection string (`postgresql+psycopg2://...`) for production, or SQLite for local testing.
- `LLM_PROVIDERS`: Ordered fallback list (default: `gemini,groq,openrouter`).
- `LLM_MODE`: Set to `real` for live inference or `mock` for deterministic test suites.
- `GEMINI_API_KEY` & `GEMINI_MODEL`: Primary Google GenAI credentials (e.g. `gemini-2.5-flash`).
- `GROQ_API_KEY` & `GROQ_MODEL`: High-speed fallback provider (e.g. `llama-3.3-70b-versatile`).
- `OPENROUTER_API_KEY` & `OPENROUTER_MODEL`: Broad fallback provider (e.g. `google/gemini-2.5-flash`).
- `DEMO_MODE`: `true` for evaluation demo builds with auto-authenticated reviewer tokens; `false` in strict production.
- `DEMO_REVIEWER_TOKEN` & `DEMO_VIEWER_TOKEN`: Evaluation bearer tokens.
- `REVIEWER_TOKENS`: Optional multi-user identity mapping (`token:email` pairs) attributed in immutable audit logs.
- `INVESTIGATION_RUN_TTL_SECONDS`: Abandoned investigation cleanup timeout (default: `180`s).

---

## Deployment & Database Migrations

- **Platform Blueprint:** Documented in [`render.yaml`](render.yaml) for Node 20 and Python 3.12 with automated `alembic upgrade head` pre-deploy and startup migration execution.
- **Production Database (Neon PostgreSQL):** The live instance at `https://fairbill-hrrg.onrender.com` runs against a hosted **Neon PostgreSQL** database. This guarantees that schema migrations, dispute cases, telemetry versions, and append-only audit events persist permanently across container restarts and redeployments.
- **Render Free-Tier Cold-Start Handling:** Render spins down free containers after 15 minutes of inactivity. The first request after an idle window takes **~45 seconds** to boot the container, displaying Render's initialization terminal. All subsequent requests execute in sub-second time. Running an external uptime ping against `/healthz` every 10 minutes keeps the instance hot.
- **Alembic vs create_all:**
  - `create_all_tables()` initializes tables and append-only database triggers for fast local testing and SQLite setups.
  - Alembic migrations (`alembic upgrade head`) manage schema evolutions in production and PostgreSQL environments.
  - Database seeding (`seed_demo_cases_if_empty`) runs idempotently after migrations on startup, inserting demo scenarios only if 0 cases exist.
