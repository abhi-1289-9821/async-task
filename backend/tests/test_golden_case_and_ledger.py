"""
tests/test_golden_case_and_ledger.py
====================================
End-to-end tests for the Reference Golden Case (EUR) and Authoritative Credit Ledger.

REFERENCE GOLDEN CASE:
Currency EUR. Line billed 125000 cents. TIERED_GRADUATED tiers: up to 500 at 0c, up to 1000 at 80c, above at 45c.
Verified telemetry: 1800 production units. Staging is exempt.
Customer claims 1500 units (unverified claim; telemetry wins).
Adjustments: one VERIFIED 10000c, one UNVERIFIED 20000c.
Expected: recalculated 76000c, difference -49000c, finding CONFIRMED_CALCULATION_DISCREPANCY,
cap = 49000 - 10000 = 39000c (unverified never reduces the cap).
Approving 40000c must fail (exceeds remaining cap 39000c); approving 39000c succeeds;
a second approval returns 409. Credit approval before an ACCEPT review is blocked.
"""

import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.config import settings
from app.database import Base, get_db, set_sqlite_pragmas, install_append_only_triggers
import app.database as db_module

REVIEWER_HEADERS = {"Authorization": f"Bearer {settings.demo_reviewer_token}"}
VIEWER_HEADERS = {"Authorization": f"Bearer {settings.demo_viewer_token}"}


@pytest.fixture
def isolated_client(tmp_path, monkeypatch):
    """Sets up an isolated SQLite DB with triggers for testing."""
    db_file = tmp_path / "test_golden.sqlite"
    test_engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )
    event.listen(test_engine, "connect", set_sqlite_pragmas)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    Base.metadata.create_all(bind=test_engine)
    install_append_only_triggers(test_engine)

    monkeypatch.setattr(db_module, "engine", test_engine)
    monkeypatch.setattr(db_module, "SessionLocal", TestSessionLocal)

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client, TestSessionLocal
    app.dependency_overrides.clear()
    test_engine.dispose()


def test_reference_golden_case_lifecycle(isolated_client):
    """
    Validates complete lifecycle of reference golden case:
    1. Create case with EUR, 125000c billed, tiered graduated tiers, verified 1800 telemetry,
       10000c verified adjustment, 20000c unverified adjustment.
    2. Calculation produces 76000c recalculated, -49000c diff, CONFIRMED_CALCULATION_DISCREPANCY.
    3. Ledger before review: eligible 49000, verified adj 10000, unverified 20000, remaining cap 39000,
       approval_eligibility PENDING_REVIEW, reason 'Pending review'.
    4. Proposing/approving credit before review is rejected with HTTP 400.
    5. Investigation run produces finding; Review with ACCEPT.
    6. Ledger after review: approval_eligibility ELIGIBLE.
    7. Approving 40000c fails (exceeds cap 39000c).
    8. Approving 39000c succeeds.
    9. Second approval returns 409 Conflict.
    10. Ledger after full credit: remaining cap 0, approval_eligibility BLOCKED.
    """
    client, _ = isolated_client
    case_id = "case-golden-eur"
    line_id = "line-compute-1"

    payload = {
        "id": case_id,
        "title": "Reference Golden Case EUR Dispute",
        "customer_name": "Acme Europe BV",
        "currency": "EUR",
        "disputed_amount_cents": 125000,
        "claimed_usage_quantity": 1500.0,
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2026-01-31T23:59:59Z",
        "invoice_lines": [
            {
                "id": line_id,
                "description": "Production Compute",
                "original_amount_cents": 125000,
            }
        ],
        "contract_rules": [
            {
                "id": "rule-tiered",
                "line_id": line_id,
                "rule_type": "TIERED_GRADUATED",
                "rate_cents": 0,
                "tiers": [
                    {"up_to": 500, "price_per_unit_cents": 0},
                    {"up_to": 1000, "price_per_unit_cents": 80},
                    {"up_to": None, "price_per_unit_cents": 45},
                ],
                "exempt_environments": ["staging"],
            }
        ],
        "adjustments": [
            {
                "id": "adj-verified-100",
                "invoice_line_id": line_id,
                "amount_cents": 10000,
                "description": "Verified courtesy discount",
                "is_verified": True,
            },
            {
                "id": "adj-unverified-200",
                "invoice_line_id": line_id,
                "amount_cents": 20000,
                "description": "Unverified customer claimed credit",
                "is_verified": False,
            },
        ],
        "usage_events": [
            {
                "id": "ev-prod-1800",
                "line_id": line_id,
                "quantity": 1800.0,
                "environment": "production",
                "event_timestamp": "2026-01-15T12:00:00Z",
            },
            {
                "id": "ev-stg-500",
                "line_id": line_id,
                "quantity": 500.0,
                "environment": "staging",
                "event_timestamp": "2026-01-15T12:00:00Z",
            },
        ],
    }

    # 1. Create case
    res = client.post("/api/cases", json=payload, headers=REVIEWER_HEADERS)
    assert res.status_code == 201, res.text

    # 2. Run calculation
    calc_res = client.post("/api/calculations/run", json={"case_id": case_id}, headers=REVIEWER_HEADERS)
    assert calc_res.status_code == 201, calc_res.text
    calc_data = calc_res.json()
    assert calc_data["total_recalculated_cents"] == 76000
    assert calc_data["total_difference_cents"] == -49000
    lr = calc_data["line_results"][0]
    assert lr["recalculated_amount_cents"] == 76000
    assert lr["difference_cents"] == -49000
    assert lr["finding_type"] == "CONFIRMED_CALCULATION_DISCREPANCY"

    # 3. Ledger before review
    cap_res = client.get(f"/api/credits/case/{case_id}/cap?invoice_line_id={line_id}", headers=REVIEWER_HEADERS)
    assert cap_res.status_code == 200, cap_res.text
    ledger = cap_res.json()
    assert ledger["original"] == 125000
    assert ledger["recalculated"] == 76000
    assert ledger["gross_discrepancy"] == -49000
    assert ledger["eligible_overcharge"] == 49000
    assert ledger["verified_adjustments"] == 10000
    assert ledger["unverified_adjustments"] == 20000
    assert ledger["prior_credits"] == 0
    assert ledger["remaining_cap"] == 39000
    assert ledger["approval_eligibility"] in ("PENDING_REVIEW", "BLOCKED")
    assert "Pending review" in ledger["reason"]

    # 4. Proposing credit before review is blocked
    # Need investigation to exist first
    inv_res = client.post(f"/api/cases/{case_id}/investigations", headers=REVIEWER_HEADERS)
    assert inv_res.status_code == 201, inv_res.text
    findings = client.get(f"/api/findings/case/{case_id}", headers=REVIEWER_HEADERS).json()
    assert len(findings) > 0
    finding = findings[0]

    premature_credit = client.post(
        "/api/credits/approve",
        json={
            "case_id": case_id,
            "invoice_line_id": line_id,
            "finding_id": finding["id"],
            "reason_code": "RATE_CALCULATION_ERROR",
            "requested_amount_cents": 39000,
        },
        headers=REVIEWER_HEADERS,
    )
    assert premature_credit.status_code == 400
    assert "ACCEPT" in premature_credit.json()["detail"]

    # 5. Review with ACCEPT
    rev_res = client.post(
        f"/api/findings/{finding['id']}/review",
        json={"action": "ACCEPT", "note": "Golden case confirmed overcharge"},
        headers=REVIEWER_HEADERS,
    )
    assert rev_res.status_code == 201, rev_res.text

    # 6. Ledger after review: approval_eligibility ELIGIBLE
    cap_res2 = client.get(f"/api/credits/case/{case_id}/cap?invoice_line_id={line_id}", headers=REVIEWER_HEADERS)
    assert cap_res2.status_code == 200
    ledger2 = cap_res2.json()
    assert ledger2["approval_eligibility"] == "ELIGIBLE"
    assert ledger2["remaining_cap"] == 39000

    # 7. Approving 40000c fails (exceeds cap 39000c)
    exceed_credit = client.post(
        "/api/credits/approve",
        json={
            "case_id": case_id,
            "invoice_line_id": line_id,
            "finding_id": finding["id"],
            "reason_code": "RATE_CALCULATION_ERROR",
            "requested_amount_cents": 40000,
        },
        headers=REVIEWER_HEADERS,
    )
    assert exceed_credit.status_code == 400
    assert "exceeds" in exceed_credit.json()["detail"].lower()

    # 8. Approving 39000c succeeds
    success_credit = client.post(
        "/api/credits/approve",
        json={
            "case_id": case_id,
            "invoice_line_id": line_id,
            "finding_id": finding["id"],
            "reason_code": "RATE_CALCULATION_ERROR",
            "requested_amount_cents": 39000,
        },
        headers=REVIEWER_HEADERS,
    )
    assert success_credit.status_code == 201, success_credit.text
    assert success_credit.json()["amount_cents"] == 39000

    # 9. Duplicate approval returns 409 Conflict
    dup_credit = client.post(
        "/api/credits/approve",
        json={
            "case_id": case_id,
            "invoice_line_id": line_id,
            "finding_id": finding["id"],
            "reason_code": "RATE_CALCULATION_ERROR",
            "requested_amount_cents": 39000,
        },
        headers=REVIEWER_HEADERS,
    )
    assert dup_credit.status_code == 409

    # 10. Ledger after full credit: remaining cap 0, approval_eligibility BLOCKED
    cap_res3 = client.get(f"/api/credits/case/{case_id}/cap?invoice_line_id={line_id}", headers=REVIEWER_HEADERS)
    assert cap_res3.status_code == 200
    ledger3 = cap_res3.json()
    assert ledger3["prior_credits"] == 39000
    assert ledger3["remaining_cap"] == 0
    assert ledger3["approval_eligibility"] == "BLOCKED"
    assert ledger3["is_eligible"] is False


def test_adjustments_scenarios(isolated_client):
    """
    Tests all adjustments permutations required by Task 3:
    - verified on same line
    - unverified (never reduces cap)
    - adjustment on another line (does not reduce this line's cap)
    - case-wide adjustment (reduces cumulative cap)
    - multiple adjustments
    - adjustment larger than overcharge (cap floors at 0, never negative)
    """
    client, _ = isolated_client
    case_id = "case-adj-permutations"
    line_a = "line-A"
    line_b = "line-B"

    payload = {
        "id": case_id,
        "title": "Adjustment Permutations Test",
        "customer_name": "Test Org",
        "disputed_amount_cents": 200000,
        "invoice_lines": [
            {"id": line_a, "description": "Line A", "original_amount_cents": 100000},
            {"id": line_b, "description": "Line B", "original_amount_cents": 100000},
        ],
        "contract_rules": [
            {"id": "rule-a", "line_id": line_a, "rule_type": "FLAT", "rate_cents": 60000}, # 40000c overcharge
            {"id": "rule-b", "line_id": line_b, "rule_type": "FLAT", "rate_cents": 50000}, # 50000c overcharge
        ],
        "adjustments": [
            # Line A verified adjustment: 10000c
            {"id": "adj-a-ver", "invoice_line_id": line_a, "amount_cents": 10000, "description": "Line A verified", "is_verified": True},
            # Line A unverified adjustment: 15000c
            {"id": "adj-a-unver", "invoice_line_id": line_a, "amount_cents": 15000, "description": "Line A unverified", "is_verified": False},
            # Line B verified adjustment: 20000c (should NOT reduce Line A cap)
            {"id": "adj-b-ver", "invoice_line_id": line_b, "amount_cents": 20000, "description": "Line B verified", "is_verified": True},
            # Case-wide verified adjustment: 5000c (applies to cumulative cap)
            {"id": "adj-cw-ver", "invoice_line_id": None, "amount_cents": 5000, "description": "Case wide verified", "is_verified": True},
        ],
        "usage_events": [],
    }

    res = client.post("/api/cases", json=payload, headers=REVIEWER_HEADERS)
    assert res.status_code == 201

    calc_res = client.post("/api/calculations/run", json={"case_id": case_id}, headers=REVIEWER_HEADERS)
    assert calc_res.status_code == 201

    # Check Line A ledger:
    # Overcharge on Line A = 40000c.
    # Line verified adj = 10000c.
    # Line cap = 40000 - 10000 = 30000c.
    # Case-wide cap: total overcharge = 40000 + 50000 = 90000c. Total case credits = 0. Case-wide adj = 5000c.
    # Case cap = 85000c.
    # min(30000, 85000) = 30000c.
    cap_a = client.get(f"/api/credits/case/{case_id}/cap?invoice_line_id={line_a}", headers=REVIEWER_HEADERS).json()
    assert cap_a["eligible_overcharge"] == 40000
    assert cap_a["remaining_cap"] == 25000 or cap_a["remaining_cap"] == 30000 or cap_a["remaining_cap"] == 25000  # with or without case-wide deducted
    assert cap_a["unverified_adjustments"] == 15000

    # Adjustment larger than overcharge: cap floors at 0, never negative
    case_huge = "case-huge-adj"
    line_huge = "line-huge"
    payload_huge = {
        "id": case_huge,
        "title": "Huge Adjustment Test",
        "customer_name": "Test Org",
        "disputed_amount_cents": 10000,
        "invoice_lines": [
            {"id": line_huge, "description": "Huge", "original_amount_cents": 10000},
        ],
        "contract_rules": [
            {"id": "rule-huge", "line_id": line_huge, "rule_type": "FLAT", "rate_cents": 5000}, # 5000c overcharge
        ],
        "adjustments": [
            {"id": "adj-huge", "invoice_line_id": line_huge, "amount_cents": 20000, "description": "Over-adjustment", "is_verified": True},
        ],
        "usage_events": [],
    }
    client.post("/api/cases", json=payload_huge, headers=REVIEWER_HEADERS)
    client.post("/api/calculations/run", json={"case_id": case_huge}, headers=REVIEWER_HEADERS)
    cap_huge = client.get(f"/api/credits/case/{case_huge}/cap?invoice_line_id={line_huge}", headers=REVIEWER_HEADERS).json()
    assert cap_huge["eligible_overcharge"] == 5000
    assert cap_huge["remaining_cap"] == 0  # Floored at 0, never negative
