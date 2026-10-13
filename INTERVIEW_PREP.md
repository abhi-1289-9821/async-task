# Interview Defense & Architecture Q&A

This document prepares technical explanations and defends design trade-offs made in the Billing Dispute Investigation and Resolution Agent project.

---

### Q1: Why use Python `Decimal` and integer cents instead of standard floating-point numbers?
**Answer:**
Binary floating-point numbers (IEEE 754) represent fractions as binary approximations. Standard numbers like `0.1` or `0.7` cannot be represented with exact precision in binary floating point. In billing systems calculating unit rates, percentage discounts, and tiered usage, floating-point arithmetic causes fractional rounding drift that accumulates over aggregations.

In this project:
- All stored monetary values and outputs are represented as **integer cents** ($10.00 = 1000$ cents).
- Calculations use Python's standard `Decimal` type with explicit quantization.
- Financial rounding occurs at the final line-item boundary using `ROUND_HALF_UP` (rounding half away from zero).

---

### Q2: Why enforce the append-only invariant at the database trigger level? What are its limits?
**Answer:**
Application-layer checks (such as omitting update methods in an ORM repository) can be bypassed by raw SQL queries, database console access, data migrations, or developer mistakes. Installing database triggers (`RAISE(ABORT)` in SQLite, trigger functions in PostgreSQL) causes the database engine itself to reject `UPDATE` and `DELETE` statements on audit tables (`case_events` and `calculation_line_results`).

**Honest Technical Limitation:**
Database triggers only guard against standard Data Manipulation Language (DML) statements. Any database administrator or privileged user with Data Definition Language (DDL) permissions can execute `DROP TRIGGER` or alter table constraints directly. Triggers protect data integrity against application errors, unintended queries, and non-privileged database clients, but they do not protect against an intentional attack by a superuser with full schema administrative rights.

---

### Q3: What is the difference between Graduated and Volume tiering?
**Answer:**
- **Tiered Graduated (Marginal):** Usage is split across tier intervals. Units within each bracket are billed at that bracket's specific rate (e.g., units 1–100 at \$0.10, units 101–500 at \$0.08).
- **Tiered Volume (Retroactive Slab):** The total usage volume determines the single tier that applies to *all* consumed units. Once usage crosses into a higher volume bracket, every unit is retroactively billed at that lower rate.

The engine implements both with inclusive upper boundaries. Furthermore, if a contract rule specifies pricing tiers without declaring whether the structure is graduated or volume, the engine flags this as `AMBIGUOUS` and outputs both concrete financial interpretations for human review.

---

### Q4: How will the system prevent double-crediting under concurrent requests? *(Planned - Phase 2)*
**Answer:**
To prevent double-crediting if two reviewers submit an approval simultaneously, the design uses three safeguards:
1. **Cryptographic Idempotency Key:** `SHA-256(case_id + invoice_line_id + reason_code)` stored in a database column with a `UNIQUE` constraint. Duplicate requests return HTTP 409 Conflict.
2. **Database Row Locking:** At transaction start, the backend acquires an exclusive row-level lock on the target invoice line (`SELECT FOR UPDATE` in PostgreSQL, `BEGIN IMMEDIATE` in SQLite) before reading the existing credit balance.
3. **Cumulative Cap Verification:** Inside the locked transaction, the service calculates:
   $$\text{Requested Credit} \le \text{Eligible Overcharge} - \sum \text{Prior Credits} - \sum \text{Historical Adjustments}$$
   If the cap is exceeded, the transaction rolls back with an error.

---

### Q5: Why separate calculation from LLM analysis?
**Answer:**
Large Language Models are probabilistic sequence models. They do not have built-in arithmetic units and frequently make errors on non-linear math, multi-tier boundaries, and percentage discounts.

In this architecture:
- All math is executed by a pure deterministic billing engine.
- Every line item calculation outputs a deterministic cryptographic anchor (`result_id`, e.g. `res_a1b2c3d4e5f67890`).
- The LLM's role in Phase 3 is restricted to reading the structured engine results, synthesizing clear human-readable explanations, and citing the exact `result_id` anchors. The LLM is never allowed to invent or alter financial amounts.
