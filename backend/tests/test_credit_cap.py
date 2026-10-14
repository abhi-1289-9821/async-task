"""
tests/test_credit_cap.py
========================
Tests for Task 3: Credit panel cap endpoint and target line.
Acceptance criteria:
  1. GET /api/credits/case/{case_id}/cap returns breakdown:
     - eligible_cents
     - prior_credits_cents
     - line_adjustments_cents
     - case_wide_adjustments_cents
     - remaining_cap_cents
  2. Line adjustments reduce line cap (tested on case-acme-101 with 500c adjustment).
  3. Case-wide adjustments reduce the cumulative case cap.
  4. Approving a credit reduces remaining_cap_cents and increases prior_credits_cents.
  5. CreditResponse includes invoice_line_id.
  6. Duplicate approval returns HTTP 409.
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
from app.models.case import Case, CaseEvent
from app.models.invoice import InvoiceLine
from app.models.investigation import InvestigationRun, Finding, FindingReview, ResolutionOption
from app.models.calculation import Calculation, CalculationLineResult, EngineStatusDB, FindingTypeDB
from app.models.credit import Credit, Adjustment

REVIEWER_HEADERS = {"Authorization": f"Bearer {settings.demo_reviewer_token}"}


@pytest.fixture
def seeded_client(tmp_path, monkeypatch):
    """Sets up an isolated SQLite DB, seeds demo cases via lifespan, yields TestClient and SessionLocal."""
    db_file = tmp_path / "test_cap.sqlite"
    test_engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )
    event.listen(test_engine, "connect", set_sqlite_pragmas)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

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


def test_cap_endpoint_with_line_adjustments(seeded_client):
    """
    case-acme-101 has:
      - billed 5000 cents, recalc 2500 cents -> overcharge = 2500 cents
      - prior line adjustment = 500 cents
    Remaining cap must be 2500 - 500 = 2000 cents.
    """
    client, _ = seeded_client

    # 1. Run calculation so line result exists
    calc_res = client.post("/api/calculations/run", json={"case_id": "case-acme-101"}, headers=REVIEWER_HEADERS)
    assert calc_res.status_code == 201

    # 2. Query cap endpoint
    res = client.get(
        "/api/credits/case/case-acme-101/cap?invoice_line_id=line-api-calls",
        headers=REVIEWER_HEADERS,
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["eligible_cents"] == 2500
    assert data["prior_credits_cents"] == 0
    assert data["line_adjustments_cents"] == 500
    assert data["case_wide_adjustments_cents"] == 0
    assert data["remaining_cap_cents"] == 2000


def test_cap_endpoint_with_case_wide_adjustments(seeded_client):
    """
    Adding a case-wide adjustment (invoice_line_id=None) reduces remaining cap.
    """
    client, SessionLocal = seeded_client

    # Run calculation
    calc_res = client.post("/api/calculations/run", json={"case_id": "case-acme-101"}, headers=REVIEWER_HEADERS)
    assert calc_res.status_code == 201

    # Insert a case-wide adjustment of 600 cents (exceeds line adjustment 500c so case_cap binds)
    with SessionLocal() as db:
        db.add(Adjustment(
            id="adj-case-wide-1",
            case_id="case-acme-101",
            invoice_line_id=None,
            amount_cents=600,
            description="Global courtesy discount",
        ))
        db.commit()

    res = client.get(
        "/api/credits/case/case-acme-101/cap?invoice_line_id=line-api-calls",
        headers=REVIEWER_HEADERS,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["eligible_cents"] == 2500
    assert data["line_adjustments_cents"] == 500
    assert data["case_wide_adjustments_cents"] == 600
    # Remaining = min(2500 - 500, 2500 - 600) = 1900
    assert data["remaining_cap_cents"] == 1900


def test_credit_approval_updates_cap_and_returns_invoice_line_id(seeded_client):
    """
    Approves credit:
      - CreditResponse includes invoice_line_id.
      - Cap endpoint reflects prior_credits and decreased remaining_cap.
      - Duplicate approval attempt returns 409 Conflict.
    """
    client, SessionLocal = seeded_client

    # Run calculation
    calc_res = client.post("/api/calculations/run", json={"case_id": "case-acme-101"}, headers=REVIEWER_HEADERS)
    calc_id = calc_res.json()["id"]

    # Create a finding and accept it
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        run = InvestigationRun(
            id="run-test-1",
            case_id="case-acme-101",
            evidence_version=1,
            status="COMPLETED",
            started_at=now,
            completed_at=now,
        )
        db.add(run)
        db.flush()

        lr = db.query(CalculationLineResult).filter(CalculationLineResult.calculation_id == calc_id).first()

        finding = Finding(
            id="find-acme-1",
            case_id="case-acme-101",
            run_id=run.id,
            calculation_line_result_id=lr.id,
            finding_type="CONFIRMED_CALCULATION_DISCREPANCY",
            raw_ai_text="Staging events were billed.",
            citation_validation_passed=True,
            consistency_check_passed=True,
            is_stale=False,
        )
        db.add(finding)
        db.flush()

        # Add ACCEPT review
        review = FindingReview(
            finding_id=finding.id,
            reviewer="reviewer_demo",
            action="ACCEPT",
            note="LGTM",
        )
        db.add(review)

        # Add resolution option
        opt = ResolutionOption(
            id="opt-acme-1",
            run_id=run.id,
            case_id="case-acme-101",
            option_type="RECOMMEND_CREDIT",
            description="Credit $10.00 for staging overcharge",
            calculation_line_result_id=lr.id,
        )
        db.add(opt)
        db.commit()

    # Approve credit of 1000 cents
    approve_res = client.post(
        "/api/credits/approve",
        headers=REVIEWER_HEADERS,
        json={
            "case_id": "case-acme-101",
            "invoice_line_id": "line-api-calls",
            "reason_code": "RATE_CALCULATION_ERROR",
            "finding_id": "find-acme-1",
            "resolution_option_id": "opt-acme-1",
            "requested_amount_cents": 1000,
        },
    )
    assert approve_res.status_code == 201, approve_res.text
    credit_data = approve_res.json()

    # 1. invoice_line_id is returned
    assert credit_data["invoice_line_id"] == "line-api-calls"
    assert credit_data["amount_cents"] == 1000

    # 2. Cap endpoint reflects updated numbers
    cap_res = client.get(
        "/api/credits/case/case-acme-101/cap?invoice_line_id=line-api-calls",
        headers=REVIEWER_HEADERS,
    )
    assert cap_res.status_code == 200
    cap_data = cap_res.json()
    assert cap_data["prior_credits_cents"] == 1000
    # Remaining = 2500 - 1000 (credit) - 500 (adjustment) = 1000
    assert cap_data["remaining_cap_cents"] == 1000

    # 3. Duplicate approval for same finding returns 409
    dup_res = client.post(
        "/api/credits/approve",
        headers=REVIEWER_HEADERS,
        json={
            "case_id": "case-acme-101",
            "invoice_line_id": "line-api-calls",
            "reason_code": "RATE_CALCULATION_ERROR",
            "finding_id": "find-acme-1",
            "resolution_option_id": "opt-acme-1",
            "requested_amount_cents": 500,
        },
    )
    assert dup_res.status_code == 409
