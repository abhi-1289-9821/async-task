# Agent Usage & Operational Guide

## Overview

The **Billing Dispute Resolution Agent** investigates B2B billing disputes by pairing a deterministic billing engine with an LLM-assisted analysis framework built on LangGraph. This architecture ensures that mathematical calculations are verifiable and immutable while the agent provides structured reasoning, evidence gap detection, and resolution recommendations.

---

## Architecture Principles

1. **Deterministic Financial Math:**
   - Calculations use Python `Decimal` with `ROUND_HALF_UP` only applied once at invoice line boundaries.
   - LLMs never compute or suggest monetary amounts. All credits reference database-persisted calculation line result rows.
2. **Untrusted Data Isolation:**
   - Customer titles and dispute descriptions are isolated within `<untrusted_customer_dispute>` and `<untrusted_line_item>` tags.
   - System prompts explicitly direct the model to treat content within these delimiters strictly as claims to audit, never as operational instructions.
3. **Citation & Consistency Verification:**
   - Every generated AI finding must cite a cryptographic engine `result_id` (format: `res_<16_hex_chars>`).
   - The validation pipeline checks that cited result IDs exist, verifies narrative consistency against actual numbers, and rejects fabricated amounts.
4. **Human Review Gate:**
   - Credits cannot be approved automatically by AI suggestions.
   - A human reviewer must explicitly `ACCEPT` a valid, non-stale finding before credit approval can proceed.
5. **Fail-Loudly in Production:**
   - When running in live mode (`LLM_MODE=real`), missing credentials or external API failures immediately raise errors and transition runs to `FAILED` instead of producing fabricated mock findings.

---

## Operational Workflows

### 1. Ingesting a Case and Evidence
1. **Case Creation (`POST /api/cases`):**
   - Provide invoice line items (`original_amount_cents`) and contract rules (`tiers`, `rate_cents`, `discount_pct`, `minimum_commit_cents`, `exempt_environments`).
   - Line and rule IDs are scoped per case, preventing cross-tenant ID collisions.
2. **Uploading Evidence (`POST /api/cases/{case_id}/evidence`):**
   - Upload usage events (`quantity`, `environment`, `line_id`).
   - Each upload bumps the case `evidence_version`, records a content hash, and invalidates older findings as stale.

### 2. Running Deterministic Calculation
- **Endpoint:** `POST /api/calculations/run`
- The engine partitions events, quarantines invalid records (negative quantity, missing/unknown line IDs, duplicates), and computes discrepancies.
- Outputs `OK`, `AMBIGUOUS` (e.g. conflicting tier models or discounts), `INSUFFICIENT_DATA`, or `PARTIAL` (if events were quarantined).

### 3. Running Agent Investigation
- **Endpoint:** `POST /api/cases/{case_id}/investigate`
- Executes the LangGraph StateGraph:
  1. `gather_evidence`: Verifies case inputs; marks `BLOCKED` if rules or lines are missing.
  2. `run_calculation`: Ensures engine calculation exists for the current evidence version.
  3. `analyze_findings`: Prompts the LLM with isolated untrusted data and deterministic results.
  4. `formulate_options`: Formulates concrete options (`RECOMMEND_CREDIT`, `ESCALATE`, `REQUEST_EVIDENCE`).
  5. `validate_and_sanitize`: Enforces regex checks for fabricated amounts, verifies citations, and validates schemas.
  6. `persist_results`: Saves immutable findings, options, and audit events.

### 4. Human-in-the-Loop Review
- **Endpoint:** `POST /api/findings/{id}/review`
- Reviewers evaluate the AI narrative and submit an action:
  - `ACCEPT`: Validates finding as authoritative for credit issuance.
  - `EDIT`: Provides human commentary while keeping the original AI text untouched.
  - `REJECT`: Dismisses the finding.

### 5. Approving Credits
- **Endpoint:** `POST /api/credits/approve`
- Enforces:
  - Caller role: `REVIEWER` (identity derived from verified token).
  - Non-stale finding with `CONFIRMED_CALCULATION_DISCREPANCY`.
  - Prior `ACCEPT` human review.
  - Passed citation validation and consistency check flags.
  - Line-level cumulative credit cap atomic check under row locking.

---

## Security & Authentication

- **Bearer Token Auth:** Supply `Authorization: Bearer <token>` on all requests.
- **Role Assignment:** Tokens are mapped to roles (`REVIEWER` or `VIEWER`) and identities in server configuration (`settings.reviewer_tokens`).
- **No Bundle Secrets:** Tokens are never baked into client JavaScript bundles. Operators enter their personal token into the frontend workspace session.
- **Append-Only Audit Log:** Database triggers block updates and deletions on `case_events`, `credits`, `calculation_line_results`, `evidence_versions`, and `finding_reviews`. In Postgres and SQLite, updates to `findings.raw_ai_text` are blocked.
