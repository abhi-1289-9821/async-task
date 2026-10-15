"""
test_api_smoke.py
=================
API Smoke Test for Task 6 CI & Verification:
  1. Create case with golden case parameters (EUR, line 125000c, TIERED_GRADUATED, 1800 units telemetry, adjustments).
  2. Calculate: run deterministic billing engine.
  3. Investigate in mock mode: autonomous investigation finds CONFIRMED_CALCULATION_DISCREPANCY.
  4. Accept finding: human reviewer reviews and accepts finding.
  5. Approve credit: verify remaining cap (39000c), reject over-approval (40000c), approve eligible 39000c.
  6. Repeat approval blocked (409 Conflict).
"""

import os
import uuid
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

REVIEWER_HEADERS = {"Authorization": f"Bearer {settings.demo_reviewer_token}"}


@pytest.fixture
def smoke_client(monkeypatch):
    monkeypatch.setattr(settings, "llm_mode", "mock")
    monkeypatch.setattr(settings, "demo_mode", True)
    with TestClient(app) as client:
        yield client


def test_end_to_end_api_smoke(smoke_client):
    uid = uuid.uuid4().hex[:8]
    case_id = f"smoke-{uid}"

    # 1. Create case (Golden Case in EUR)
    payload = {
        "id": case_id,
        "title": "Smoke Test Golden EUR Dispute",
        "customer_name": "Acme Europe BV",
        "currency": "EUR",
        "disputed_amount_cents": 49000,
        "dispute_description": "Rate tier calculation mismatch on telemetry usage",
        "invoice_lines": [
            {
                "id": f"line-{case_id}-1",
                "description": "Compute Units Tiered",
                "original_amount_cents": 125000,
            }
        ],
        "contract_rules": [
            {
                "id": f"rule-{case_id}-1",
                "line_id": f"line-{case_id}-1",
                "rule_type": "TIERED_GRADUATED",
                "tiers": [
                    {"up_to": 500, "price_per_unit_cents": 0},
                    {"up_to": 1000, "price_per_unit_cents": 80},
                    {"up_to": None, "price_per_unit_cents": 45},
                ],
                "exempt_environments": ["staging"],
            }
        ],
        "usage_events": [
            {
                "id": f"ev-{case_id}-prod",
                "line_id": f"line-{case_id}-1",
                "quantity": 1800.0,
                "environment": "production",
            },
            {
                "id": f"ev-{case_id}-stg",
                "line_id": f"line-{case_id}-1",
                "quantity": 200.0,
                "environment": "staging",
            },
        ],
        "adjustments": [
            {
                "id": f"adj-{case_id}-verified",
                "invoice_line_id": f"line-{case_id}-1",
                "amount_cents": 10000,
                "description": "Verified promo credit",
                "is_verified": True,
            },
            {
                "id": f"adj-{case_id}-unverified",
                "invoice_line_id": f"line-{case_id}-1",
                "amount_cents": 20000,
                "description": "Unverified concession claim",
                "is_verified": False,
            },
        ],
    }

    # Clean up any existing case
    c_res = smoke_client.post("/api/cases", json=payload, headers=REVIEWER_HEADERS)
    assert c_res.status_code in (201, 200), f"Create case failed: {c_res.text}"

    line_id = f"line-{case_id}-1"

    # Verify initial ledger before calculation / review
    cap_res = smoke_client.get(f"/api/credits/case/{case_id}/cap?invoice_line_id={line_id}", headers=REVIEWER_HEADERS)
    assert cap_res.status_code == 200
    ledger0 = cap_res.json()
    assert ledger0["approval_eligibility"] == "PENDING_REVIEW"
    assert ledger0["remaining_cap"] == 0

    # 2. Run deterministic calculation
    calc_res = smoke_client.post("/api/calculations/run", json={"case_id": case_id}, headers=REVIEWER_HEADERS)
    assert calc_res.status_code in (200, 201), f"Calculate failed: {calc_res.text}"
    calc_data = calc_res.json()
    assert calc_data["total_original_billed_cents"] == 125000
    assert calc_data["total_recalculated_cents"] == 76000
    assert calc_data["total_difference_cents"] == -49000

    # 3. Trigger autonomous investigation in mock mode
    inv_res = smoke_client.post(f"/api/cases/{case_id}/investigations", headers=REVIEWER_HEADERS)
    assert inv_res.status_code in (200, 201), f"Investigate failed: {inv_res.text}"
    inv_data = inv_res.json()
    assert inv_data["status"] == "COMPLETED"

    findings_res = smoke_client.get(f"/api/findings/case/{case_id}", headers=REVIEWER_HEADERS)
    assert findings_res.status_code == 200
    findings = findings_res.json()
    assert len(findings) >= 1
    target_finding = findings[0]
    assert target_finding["finding_type"] == "CONFIRMED_CALCULATION_DISCREPANCY"
    finding_id = target_finding["id"]

    # 4. Human Reviewer accepts finding
    rev_res = smoke_client.post(
        f"/api/findings/{finding_id}/review",
        json={"action": "ACCEPT", "note": "Verified calculation error confirmed against contract telemetry."},
        headers=REVIEWER_HEADERS,
    )
    assert rev_res.status_code == 201, f"Review failed: {rev_res.text}"

    # 5. Check credit cap after ACCEPT
    cap_after = smoke_client.get(f"/api/credits/case/{case_id}/cap?invoice_line_id={line_id}", headers=REVIEWER_HEADERS)
    assert cap_after.status_code == 200
    ledger_after = cap_after.json()
    assert ledger_after["approval_eligibility"] == "ELIGIBLE"
    assert ledger_after["remaining_cap"] == 39000  # 49000 - 10000 = 39000
    assert ledger_after["verified_adjustments"] == 10000
    assert ledger_after["unverified_adjustments"] == 20000

    # 6. Approving credit exceeding cap (40000c) must fail
    over_res = smoke_client.post(
        "/api/credits/approve",
        json={
            "case_id": case_id,
            "invoice_line_id": line_id,
            "requested_amount_cents": 40000,
            "reason_code": "RATE_CALCULATION_ERROR",
            "reason_note": "Attempted over-approval",
            "idempotency_key": f"idem-{case_id}-over",
            "finding_id": finding_id,
        },
        headers=REVIEWER_HEADERS,
    )
    assert over_res.status_code in (400, 422)

    # 7. Approving exact allowable cap (39000c) must succeed
    ok_res = smoke_client.post(
        "/api/credits/approve",
        json={
            "case_id": case_id,
            "invoice_line_id": line_id,
            "requested_amount_cents": 39000,
            "reason_code": "RATE_CALCULATION_ERROR",
            "reason_note": "Final allowable credit issuance",
            "idempotency_key": f"idem-{case_id}-valid",
            "finding_id": finding_id,
        },
        headers=REVIEWER_HEADERS,
    )
    assert ok_res.status_code == 201, f"Credit approval failed: {ok_res.text}"

    # 8. Repeat approval returns 409
    dup_res = smoke_client.post(
        "/api/credits/approve",
        json={
            "case_id": case_id,
            "invoice_line_id": line_id,
            "requested_amount_cents": 39000,
            "reason_code": "RATE_CALCULATION_ERROR",
            "reason_note": "Duplicate credit issuance attempt",
            "idempotency_key": f"idem-{case_id}-valid",
            "finding_id": finding_id,
        },
        headers=REVIEWER_HEADERS,
    )
    assert dup_res.status_code == 409
