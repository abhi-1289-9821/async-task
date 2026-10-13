# Billing Dispute Investigation and Resolution Agent

An interview-ready, full-stack AI-assisted platform for investigating and resolving complex billing disputes with a deterministic pricing engine, human-in-the-loop review, and immutable audit logging.

---

## Architecture Overview

```
                                      ┌─────────────────────────────────┐
                                      │        FastAPI Backend          │
                                      │   (State Machine & Audit Log)   │
                                      └──────────────┬──────────────────┘
                                                     │
                         ┌───────────────────────────┴───────────────────────────┐
                         ▼                                                       ▼
            ┌───────────────────────────┐                           ┌───────────────────────────┐
            │   Billing Engine (Pure)   │                           │    Agentic Investigation  │
            │  - Decimal, ROUND_HALF_UP │                           │  - LangGraph Orchestrator │
            │  - Graduated & Volume     │                           │  - Gemini Analysis        │
            │  - Overage & Exemptions   │                           │  - Human-in-the-loop Gate │
            │  - SHA-256 Anchored Res   │                           │  - Immutable Reviews      │
            └───────────────────────────┘                           └───────────────────────────┘
```

### Key Principles

1. **Deterministic Calculation vs. Generative Analysis**
   - Financial numbers are NEVER calculated by the LLM.
   - The deterministic engine evaluates contract rules, pricing tiers, environment exemptions, and overages using `Decimal` and `ROUND_HALF_UP` in integer cents.
   - The AI agent synthesizes findings and draft explanations, citing engine result anchors (`result_id`).

2. **Immutable Audit Trail**
   - All events and calculation outputs are strictly append-only.
   - Enforced at the database level via triggers blocking `UPDATE` and `DELETE` on `case_events` and `calculation_line_results`.

3. **Concurrency-Safe Idempotent Credits**
   - Credits require explicit reviewer approval of a non-stale finding.
   - Idempotency enforced via SHA-256 keys and row-level locking (`SELECT FOR UPDATE` on PostgreSQL / `BEGIN IMMEDIATE` on SQLite) to prevent double-crediting under concurrent requests.

---

## Project Structure

```
d:\agg\
├── backend/
│   ├── app/
│   │   ├── billing_engine.py      # Pure deterministic billing calculation engine
│   │   ├── config.py              # Pydantic-settings environment configuration
│   │   ├── database.py            # SQLite/PostgreSQL setup, WAL mode, DB triggers
│   │   ├── models/                # SQLAlchemy models (Case, Invoice, Usage, etc.)
│   │   ├── routers/               # API routes (Cases, Evidence, Engine, Credits)
│   │   ├── schemas/               # Pydantic validation schemas
│   │   └── services/              # Transition service, Credit service, etc.
│   ├── tests/
│   │   ├── test_billing_engine.py # 53 unit tests for pricing & edge cases
│   │   └── test_models_and_db.py  # Tests for schema, foreign keys & DB triggers
│   ├── pytest.ini
│   └── requirements.txt
├── docs/
│   └── agent_log.md               # Append-only engineering log
├── .env.example
├── .gitignore
└── README.md
```

---

## Quickstart

### 1. Setup Backend Virtual Environment
```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Run Tests
```bash
pytest -v
```
All 60 unit tests pass in ~1.3 seconds with 0 warnings.

---

## Current Status

- [x] **Phase 0**: Architecture design, technical risk evaluation, and contract specification.
- [x] **Phase 1**: Deterministic billing calculation engine, SQLAlchemy ORM models, append-only database triggers, and unit tests (60/60 passing).
- [ ] **Phase 2**: FastAPI state machine, review & credit approval services, concurrency locking tests, and deployment scripts.
- [ ] **Phase 3**: LangGraph multi-step investigation agent with Gemini integration and mock fallback.
- [ ] **Phase 4**: Frontend audit workspace (React / Vite).
- [ ] **Phase 5**: End-to-end evaluation, live scenario demonstrations, and submission artifacts.
