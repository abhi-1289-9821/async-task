# Billing Dispute Investigation & Resolution Agent

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)
[![Tests](https://img.shields.io/badge/pytest-60%2F60%20passed-brightgreen.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

An enterprise-grade, interview-ready full-stack AI system designed to autonomously investigate, recalculate, and resolve complex SaaS and cloud infrastructure billing disputes. Built with an uncompromising focus on **financial determinism**, **immutable audit trails**, **human-in-the-loop review**, and **concurrency safety**.

---

## 📑 Table of Contents

- [The Problem & Architectural Motivation](#-the-problem--architectural-motivation)
- [How This Project Differs From Typical Submissions](#-how-this-project-differs-from-typical-submissions)
- [System Architecture](#-system-architecture)
- [Core Engineering Pillars](#-core-engineering-pillars)
  - [1. Pure Deterministic Billing Engine](#1-pure-deterministic-billing-engine)
  - [2. Database-Enforced Append-Only Audit Trail](#2-database-enforced-append-only-audit-trail)
  - [3. Human-in-the-Loop Review Architecture](#3-human-in-the-loop-review-architecture)
  - [4. Concurrency-Safe, Idempotent Credit Approval](#4-concurrency-safe-idempotent-credit-approval)
  - [5. Staleness & Versioned Evidence Tracking](#5-staleness--versioned-evidence-tracking)
- [Database Schema (14 Tables)](#-database-schema-14-tables)
- [Test Suite & Quality Verification](#-test-suite--quality-verification)
- [Quickstart & Local Development](#-quickstart--local-development)
- [Implementation Roadmap](#-implementation-roadmap)
- [Interview Defense & Architecture Q&A](#-interview-defense--architecture-qa)
- [Engineering Log & Transparency](#-engineering-log--transparency)

---

## 🎯 The Problem & Architectural Motivation

In modern cloud and enterprise SaaS billing (AWS, Snowflake, Twilio, Datadog), billing disputes are ubiquitous, high-stakes, and computationally intricate. A single monthly bill may involve:
- Thousands of metered usage events across multiple environments (production, staging, dev).
- Non-linear pricing structures: graduated marginal tiers, volume retroactive slabs, minimum spend commitments, and contractual percentage discounts.
- Edge conditions: exempt staging environments, malformed or negative usage metrics, and ambiguous contractual clauses.

### Why Naive "GenAI-Only" Approaches Fail
Most LLM-based billing tools fail in enterprise audits because:
1. **Arithmetic Hallucinations:** LLMs cannot reliably perform multi-tier mathematical calculations or financial rounding.
2. **Lack of Idempotency:** Running the same dispute twice produces different explanations and conflicting financial recommendations.
3. **Audit Liability:** If an AI model hallucinatingly credits $10,000, there is no verifiable mathematical proof or deterministic citation anchor.
4. **Race Conditions:** Naive credit issuance APIs double-credit customers under concurrent web requests.

### The Solution: Hybrid Determinism + Agentic Orchestration
This system separates **calculation** from **investigation**:
- **Math is 100% Deterministic:** Executed in pure Python using `Decimal`, integer cents, and strict `ROUND_HALF_UP` rounding. The LLM is **never** permitted to calculate numbers or formulate financial amounts.
- **AI is 100% Citational:** LangGraph multi-node agents synthesize narrative explanations and draft correspondence, strictly constrained to cite deterministic calculation anchors (`result_id`).
- **Humans Gate Financial Action:** Credits require explicit reviewer authorization on accepted, non-stale findings.

---

## ⚔️ How This Project Differs From Typical Submissions

| Dimension | Typical / Toy Project | This Engineering Solution |
| :--- | :--- | :--- |
| **Financial Arithmetic** | Floating-point numbers (`float`), prone to IEEE 754 precision drift. | **Integer Cents & Decimal**: Zero floating-point representation. Pure `ROUND_HALF_UP` boundary math. |
| **Pricing Models** | Simple flat unit rates (`qty * rate`). | **Comprehensive Real-World Models**: Flat, Per-Unit, Tiered Graduated (marginal), Tiered Volume (retroactive slab), Included Units + Overage, Percentage Discounts, and Minimum Spend Commitments. |
| **Ambiguity & Quarantine** | Crashes on bad data or silently drops rows. | **Defensive Error Handling**: Quarantines malformed/negative usage without aborting calculation (`PARTIAL`). Generates dual mathematical interpretations when contract terms are underspecified (`AMBIGUOUS`). |
| **Audit Log Integrity** | Application-level logger or standard SQL table that can be overwritten. | **Physical DB Triggers**: Append-only invariant enforced at the database level (`RAISE(ABORT)` in SQLite, trigger functions in PostgreSQL). `UPDATE` and `DELETE` queries are physically blocked. |
| **AI Decision Boundary** | LLM outputs credit amount and auto-refunds. | **Rigid Boundary Separation**: LLM amount comes exclusively from engine lookup. Raw AI output is preserved while human edits are captured separately in `FindingReview`. |
| **Double-Crediting Safety** | Vulnerable to race conditions under concurrent clicks. | **Database Row Locking**: Atomic evaluation using `SELECT FOR UPDATE` (PostgreSQL) / `BEGIN IMMEDIATE` (SQLite) + SHA-256 idempotency keys + cumulative credit cap enforcement. |
| **Code Integrity** | Unpinned dependencies, hidden AI errors. | **Audited Engineering Log**: Pinned Python 3.12 dependencies, explicit root-cause analysis in `docs/agent_log.md`, zero warnings across 60 unit tests. |

---

## 🏛️ System Architecture

```
                                  ┌─────────────────────────────────────────┐
                                  │           FastAPI Web Service           │
                                  │    (Bearer Auth, Role Enforcement)      │
                                  └────────────────────┬────────────────────┘
                                                       │
         ┌─────────────────────────────────────────────┼─────────────────────────────────────────────┐
         ▼                                             ▼                                             ▼
┌─────────────────────────────────┐       ┌─────────────────────────────────┐       ┌─────────────────────────────────┐
│     Deterministic Engine        │       │      Agentic Investigation      │       │     Credit Approval Service     │
│  - Zero float arithmetic        │       │  - LangGraph state orchestrator │       │  - Row-level lock concurrency   │
│  - Graduated vs Volume tiers    │       │  - Google Gemini API            │       │  - Cumulative credit cap check  │
│  - Included units & overage     │       │  - Deterministic citation check │       │  - SHA-256 idempotency key      │
│  - Malformed usage quarantine   │       │  - Human review audit table     │       │  - Atomic balance reduction     │
│  - Deterministic result hash    │       │  - Preserves raw vs edited text │       │  - Block duplicate requests     │
└────────────────┬────────────────┘       └────────────────┬────────────────┘       └────────────────┬────────────────┘
                 │                                         │                                         │
                 └─────────────────────────────────────────┼─────────────────────────────────────────┘
                                                           ▼
                                  ┌─────────────────────────────────────────┐
                                  │          Relational Storage             │
                                  │      (SQLite WAL / PostgreSQL)          │
                                  │   - 14 Normalized Tables                │
                                  │   - PRAGMA foreign_keys = ON            │
                                  │   - Append-Only DB Triggers             │
                                  └─────────────────────────────────────────┘
```

---

## 🔧 Core Engineering Pillars

### 1. Pure Deterministic Billing Engine
Implemented in [`backend/app/billing_engine.py`](file:///d:/agg/backend/app/billing_engine.py):
- **Zero Floating-Point Drift:** Uses Python's standard `Decimal` class. Intermediate calculations are performed in high precision and rounded to integer cents via `ROUND_HALF_UP`.
- **Supported Pricing Structures:**
  - `FLAT`: Fixed charge independent of usage.
  - `PER_UNIT`: Single unit price applied across aggregated billable quantity.
  - `TIERED_GRADUATED`: Marginal tiering where usage spans multiple pricing brackets (e.g., units 1–100 @ $10, 101–500 @ $8).
  - `TIERED_VOLUME`: Retroactive slab tiering where total volume determines the unit price for *all* units, with upper boundaries evaluated inclusively.
  - `INCLUDED_UNITS`: Free tier allowance with dedicated overage unit rates.
  - `DISCOUNT_PCT`: Percentage discount applied after tier evaluation.
  - `MINIMUM_COMMIT`: Enforces minimum contract spend floor after discounts.
- **Defensive Data Handling:**
  - **Quarantine:** Negative usage records are isolated and logged with specific reasons, allowing the remainder of the invoice to compute under `PARTIAL` status.
  - **Ambiguity Detection:** Underspecified contracts (e.g., tier type not stated) trigger deterministic branching, generating multiple concrete financial interpretations under `AMBIGUOUS` status.
  - **Repeatable Citation Anchors:** Emits an immutable `result_id` (format: `res_` + 16-hex SHA-256 hash of normalized inputs) for every line item, allowing the AI agent to cite exact calculations.

### 2. Database-Enforced Append-Only Audit Trail
Implemented in [`backend/app/database.py`](file:///d:/agg/backend/app/database.py):
- Critical tables (`case_events` and `calculation_line_results`) are physically immutable.
- Rather than relying on application code conventions, immutability is enforced via database triggers:
  ```sql
  CREATE TRIGGER trg_case_events_no_update
  BEFORE UPDATE ON case_events
  BEGIN
      SELECT RAISE(ABORT, 'case_events is append-only: UPDATE is not permitted');
  END;

  CREATE TRIGGER trg_case_events_no_delete
  BEFORE DELETE ON case_events
  BEGIN
      SELECT RAISE(ABORT, 'case_events is append-only: DELETE is not permitted');
  END;
  ```
- Any rogue `UPDATE` or `DELETE` query (from bugs, scripts, or malicious actors) triggers an `IntegrityError` at the database engine level.

### 3. Human-in-the-Loop Review Architecture
Implemented in [`backend/app/models/investigation.py`](file:///d:/agg/backend/app/models/investigation.py):
- AI outputs are never treated as authoritative business decisions.
- Findings generated by the investigation agent must pass through the `finding_reviews` table.
- Original AI generated text is **permanently preserved**; reviewer adjustments, notes, and final text are recorded separately along with the reviewer's identity and timestamp.
- Available review states: `ACCEPT`, `EDIT`, `REJECT`. Credit approval strictly requires an `ACCEPTED` non-stale finding.

### 4. Concurrency-Safe, Idempotent Credit Approval
Implemented in [`backend/app/models/credit.py`](file:///d:/agg/backend/app/models/credit.py):
- **Deterministic Idempotency Key:** `SHA-256(case_id + invoice_line_id + reason_code)` with a unique constraint in the database.
- **Race Condition Prevention:**
  - PostgreSQL: Acquires an exclusive row-level lock via `SELECT FOR UPDATE` on the invoice line.
  - SQLite: Executes inside a `BEGIN IMMEDIATE` transaction.
- **Cumulative Cap Invariant:** Verifies that:
  $$\text{Requested Credit} \le \text{Eligible Overcharge} - \sum \text{Prior Credits} - \sum \text{Contract Adjustments}$$
  Under concurrent execution, duplicate requests return HTTP `409 Conflict`.

### 5. Staleness & Versioned Evidence Tracking
- Any upload of new evidence (new usage CSV, updated contract rule) increments `evidence_version` on the case.
- Any finding, calculation, or resolution option linked to an earlier version is flagged as `is_stale = True`.
- Credit approvals automatically reject stale findings, prompting the user or agent to re-run investigation on the latest snapshot.

---

## 🗄️ Database Schema (14 Tables)

All tables use explicit foreign key constraints, indexes on lookup keys, and JSON support for tiered structures:

```
├── Cases & Audit
│   ├── cases                      # Core dispute records, status, and evidence version
│   └── case_events                # Append-only audit trail (immutable via trigger)
│
├── Invoices & Contracts
│   ├── invoice_lines              # Disputed line items and original billed amounts
│   └── contract_rules             # Pricing rules, JSON tiers, exemptions, discounts
│
├── Usage & Evidence Snapshots
│   ├── usage_events               # Metered usage records, quantities, and environments
│   └── evidence_versions          # Cryptographic SHA-256 snapshot of inputs
│
├── Deterministic Calculations
│   ├── calculations               # Engine run metadata, engine version, total diff
│   └── calculation_line_results   # Line-level calculation outputs (immutable via trigger)
│
├── Investigation & Review
│   ├── investigation_runs         # LangGraph execution runs and statuses
│   ├── findings                   # AI findings linked to calculation result anchors
│   ├── finding_reviews            # Human review decisions (ACCEPT/EDIT/REJECT)
│   └── resolution_options         # Proposed resolution actions (credit, explanation)
│
└── Credits & Accounting
    ├── credits                    # Approved mock credits (idempotent, capped)
    └── adjustments                # Historical account credits applied prior to dispute
```

---

## 🧪 Test Suite & Quality Verification

The test suite runs under `pytest` with 100% deterministic reproducibility:

```bash
pytest -v
```

### Breakdown of Current 60 Passing Tests:
- **`TestRoundCents` (6 tests):** Validates `ROUND_HALF_UP` behavior, exact integer handling, and boundary rounding at $0.5$.
- **`TestFlat` (3 tests):** Validates flat fee billing and usage invariance.
- **`TestPerUnit` (4 tests):** Validates linear unit pricing, overcharge calculation, and multi-event aggregation.
- **`TestTieredGraduated` (5 tests):** Validates marginal tier step-functions across 1st, 2nd, and 3rd tier boundaries.
- **`TestTieredVolume` (4 tests):** Validates retroactive slab tiers and proves different financial output compared to graduated tiering on identical usage.
- **`TestIncludedUnits` (5 tests):** Validates free allowances, exact boundary thresholds, and overage rate application.
- **`TestDiscount` (3 tests):** Validates percentage discount math, rounding at fractional boundaries, and ambiguity triggers on multiple discounts.
- **`TestMinimumCommit` (4 tests):** Validates minimum spend floor enforcement and evaluation order (discount $\rightarrow$ minimum commit).
- **`TestEnvironmentExemptions` (4 tests):** Validates exclusion of staging/dev usage and zero-bill assertions when all usage is exempt.
- **`TestQuarantine` (4 tests):** Validates isolation of negative usage, structured quarantine reason logging, and `PARTIAL` engine status.
- **`TestMissingRule` (2 tests):** Validates graceful handling of unmapped lines returning `INSUFFICIENT_DATA`.
- **`TestAmbiguousTierType` (3 tests):** Validates dual interpretation generation and `AMBIGUOUS` engine status.
- **`TestRepeatability` (3 tests):** Validates cryptographic repeatability of `result_id` and `result_hash` across identical runs.
- **`TestRunCalculation` (3 tests):** Validates total reconciliation and multi-line invoice aggregations.
- **`TestDatabaseSchemaAndConstraints` (7 tests):**
  - Confirms creation of all 14 database tables.
  - Verifies SQLite foreign key enforcement (`PRAGMA foreign_keys = ON`).
  - Confirms `case_events` append-only trigger prevents `UPDATE` and `DELETE`.
  - Confirms `calculation_line_results` trigger blocks modifications.
  - Validates `Credit` idempotency key unique constraint.
  - Validates JSON column serialization and deserialization.

---

## 🚀 Quickstart & Local Development

### Prerequisites
- Python 3.12+
- Git

### 1. Clone & Enter Repository
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
DEMO_AUTH_TOKEN=demo-reviewer-token-2026
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash
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

### 4. Run the Full Test Suite
```bash
pytest -v
```

---

## 🗺️ Implementation Roadmap

- [x] **Phase 0: Architecture & Risk Evaluation**
  - Specification of business rules, rounding invariants, pricing models, and technical risks.
- [x] **Phase 1: Deterministic Engine & Core Schema**
  - Pure calculation engine (`Decimal`, `ROUND_HALF_UP`), 14 SQLAlchemy ORM models, append-only triggers, 60 passing tests.
- [ ] **Phase 2: FastAPI Backend, Audit Log & State Machine**
  - API routers, transition validation (invalid $\rightarrow$ 409), credit approval service with locking, Render/Neon deployment configuration.
- [ ] **Phase 3: Agentic Investigation (LangGraph + Gemini)**
  - Two-phase investigation workflow, deterministic citation guardrails, mock/real LLM toggles, evidence-gathering abort logic.
- [ ] **Phase 4: Frontend Audit Workspace (React + Vite)**
  - Visual timeline, invoice discrepancy breakdown, side-by-side human review editor, interactive credit approval interface.
- [ ] **Phase 5: Evaluation Scenarios & Final Submission**
  - 6 end-to-end benchmark scenarios (overcharges, volume tiers, staging exemptions, prompt injection defense, concurrency tests).

---

## 💬 Interview Defense & Architecture Q&A

#### Q1: Why use Python `Decimal` and integer cents instead of standard floating-point numbers?
> **Answer:** Binary floating-point numbers (IEEE 754) cannot represent base-10 fractions (such as 0.1 or 0.7) exactly. When performing aggregations over millions of usage events or computing tiered slabs, rounding drift accumulates and causes legal and compliance discrepancies. We store all financial values as integer cents ($10.00 = 1000$ cents) and execute calculations using `Decimal` with explicit `ROUND_HALF_UP` semantics.

#### Q2: Why enforce the append-only invariant at the database trigger level instead of in the ORM?
> **Answer:** Application-layer checks can be bypassed by raw SQL statements, database migration scripts, administrative consoles, or ORM update bugs. A database trigger with `RAISE(ABORT)` makes the table physically immutable at the storage engine level, providing mathematical guarantees for compliance audits (SOC 2, ISO 27001).

#### Q3: What is the fundamental difference between Graduated and Volume tiering?
> **Answer:** Graduated tiering is marginal: usage is sliced across tier brackets, and each bracket is priced at its own rate. Volume tiering is a retroactive cliff: once total volume crosses a tier threshold, all units are retroactively priced at that lower rate. Our engine explicitly handles both, with inclusive upper bounds, and flags underspecified contracts with an `AMBIGUOUS` status.

#### Q4: How do you prevent double-crediting if two reviewers click "Approve Credit" simultaneously?
> **Answer:** We combine three layers:
> 1. A cryptographic idempotency key: `SHA-256(case_id + line_id + reason_code)` with a unique constraint in the DB.
> 2. Concurrency locking: `SELECT FOR UPDATE` on PostgreSQL or `BEGIN IMMEDIATE` on SQLite to lock the row during evaluation.
> 3. Atomic cumulative cap checking: verifying that the approved amount does not exceed the remaining eligible overcharge balance.

#### Q5: Why shouldn't an LLM calculate the refund amount directly?
> **Answer:** Large Language Models are probabilistic next-token predictors. They have no internal arithmetic unit and frequently produce subtle, non-deterministic calculation errors. In our architecture, the LLM is restricted to narrative synthesis and evidence citation. The dollar amount for any credit recommendation is strictly retrieved from the deterministic `calculation_line_result_id`.

---

## 📜 Engineering Log & Transparency

To ensure complete transparency and code defense, every technical decision, rejected assumption, and error correction is recorded chronologically in [`docs/agent_log.md`](file:///d:/agg/docs/agent_log.md).

Key recorded engineering events include:
- **Dependency Conflict Resolution:** Reconciled `langchain-core` and `pydantic` version pins against `langgraph` and `google-genai` prior to writing application code.
- **Negative Rounding Correction:** Documented Python's `Decimal` `ROUND_HALF_UP` behavior on negative boundaries (rounds away from zero, so $-0.5 \rightarrow -1$).
- **SQLite Trigger Exception Mapping:** Documented that SQLite translates `RAISE(ABORT)` triggers to `sqlite3.IntegrityError` (wrapped by SQLAlchemy as `sqlalchemy.exc.IntegrityError`), ensuring correct test assertions.
