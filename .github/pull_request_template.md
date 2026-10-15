## Description
<!-- Provide a brief overview of changes and why they are necessary. -->

## Pre-Merge Quality & Anti-Regression Checklist

Please ensure all checkboxes are verified prior to requesting review or merging:

- [ ] **Golden Case Passes**: Verified EUR reference case (125,000c billed, 1,800 units, 76,000c recalculated, -49,000c discrepancy, 10,000c verified adjustment, 39,000c allowable recovery cap).
- [ ] **Scenario Matrix Suite Passes**: `pytest backend/tests/test_anti_regression_matrix.py` passes all Hypothesis property tests across USD/EUR/GBP, all 7 rule types, multi-line, adjustments, and billing period scenarios.
- [ ] **No Hardcoded Currency**: Vitest currency guard passes; no hardcoded `$`, `toFixed(2)`, or `($ USD)` in frontend; all money values are formatted via `formatMoney(cents, currency)`.
- [ ] **No Frontend Money Math**: Frontend strictly displays backend ledger values; caps, eligible overcharges, and adjustments are never computed or recomputed in frontend code.
- [ ] **Deterministic Engine Math Preserved**: `backend/app/billing_engine.py` standard library `Decimal`, integer cents, and `ROUND_HALF_UP` invariants untouched.
- [ ] **Database Schema & Migrations Synchronized**: `alembic upgrade head` on a clean PostgreSQL database executes without errors and `alembic check` reports zero drift.
- [ ] **CI & Lint Clean**: `pytest` (plain, no env vars needed) and `npm run lint && npm run test && npm run build` pass with zero errors.
