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


def test_credit_approval_undisputed_portion_ambiguity(seeded_client):
    """
    case-bravo-102 has AMBIGUOUS line line-data-processing (billed 4000 cents).
    Interpretations: 2500 and 2000 cents -> undisputed minimum overcharge = 1500 cents.
    Reviewer can approve credit for CREDIT_UNDISPUTED_PORTION up to 1500 cents.
    Cap enforcement: requesting 1600 cents fails with 400.
    """
    client, SessionLocal = seeded_client

    # 1. Run calculation
    calc_res = client.post("/api/calculations/run", json={"case_id": "case-bravo-102"}, headers=REVIEWER_HEADERS)
    assert calc_res.status_code == 201

    with SessionLocal() as db:
        calc = db.query(Calculation).filter(Calculation.case_id == "case-bravo-102").first()
        lr = db.query(CalculationLineResult).filter(CalculationLineResult.calculation_id == calc.id).first()
        assert lr.finding_type == FindingTypeDB.AMBIGUOUS
        assert lr.undisputed_overcharge_cents == 1500

        run = InvestigationRun(
            id="run-bravo-test",
            case_id="case-bravo-102",
            calculation_id=calc.id,
            status="COMPLETED",
            evidence_version=1,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        db.add(run)

        finding = Finding(
            id="find-bravo-1",
            case_id="case-bravo-102",
            run_id=run.id,
            calculation_line_result_id=lr.id,
            finding_type="CONTRACT_AMBIGUITY",
            narrative="Ambiguous tier clause; undisputed minimum overcharge is 1500c.",
            raw_ai_text="Ambiguous tier clause",
            citation_validation_passed=True,
            consistency_check_passed=True,
            is_stale=False,
        )
        db.add(finding)

        review = FindingReview(
            finding_id=finding.id,
            reviewer="reviewer_demo",
            action="ACCEPT",
            note="Accept undisputed credit portion",
        )
        db.add(review)

        opt = ResolutionOption(
            id="opt-bravo-undisputed",
            run_id=run.id,
            case_id="case-bravo-102",
            option_type="CREDIT_UNDISPUTED_PORTION",
            description="Credit undisputed minimum overcharge of 1500c",
            calculation_line_result_id=lr.id,
        )
        db.add(opt)
        db.commit()

    # Cap check endpoint
    cap_res = client.get(
        "/api/credits/case/case-bravo-102/cap?invoice_line_id=line-compute-units",
        headers=REVIEWER_HEADERS,
    )
    assert cap_res.status_code == 200
    assert cap_res.json()["remaining_cap_cents"] == 1500

    # Over-cap request fails
    over_res = client.post(
        "/api/credits/approve",
        headers=REVIEWER_HEADERS,
        json={
            "case_id": "case-bravo-102",
            "invoice_line_id": "line-compute-units",
            "reason_code": "CONTRACT_AMBIGUITY_UNDISPUTED",
            "finding_id": "find-bravo-1",
            "resolution_option_id": "opt-bravo-undisputed",
            "requested_amount_cents": 1600,
        },
    )
    assert over_res.status_code == 400
    assert "exceeds remaining cap" in over_res.text

    # Valid request succeeds with deterministic stored amount
    approve_res = client.post(
        "/api/credits/approve",
        headers=REVIEWER_HEADERS,
        json={
            "case_id": "case-bravo-102",
            "invoice_line_id": "line-compute-units",
            "reason_code": "CONTRACT_AMBIGUITY_UNDISPUTED",
            "finding_id": "find-bravo-1",
            "resolution_option_id": "opt-bravo-undisputed",
            "requested_amount_cents": 1500,
        },
    )
    assert approve_res.status_code == 201
    assert approve_res.json()["amount_cents"] == 1500

    # Duplicate credit returns 409
    dup_res = client.post(
        "/api/credits/approve",
        headers=REVIEWER_HEADERS,
        json={
            "case_id": "case-bravo-102",
            "invoice_line_id": "line-compute-units",
            "reason_code": "CONTRACT_AMBIGUITY_UNDISPUTED",
            "finding_id": "find-bravo-1",
            "resolution_option_id": "opt-bravo-undisputed",
            "requested_amount_cents": 1000,
        },
    )
    assert dup_res.status_code == 409


def test_second_credit_on_same_finding_with_different_custom_key_returns_409(seeded_client):
    """
    Even with different custom idempotency keys, a finding can only receive one credit.
    """
    client, SessionLocal = seeded_client

    calc_res = client.post("/api/calculations/run", json={"case_id": "case-acme-101"}, headers=REVIEWER_HEADERS)
    assert calc_res.status_code == 201

    with SessionLocal() as db:
        calc = db.query(Calculation).filter(Calculation.case_id == "case-acme-101").first()
        lr = db.query(CalculationLineResult).filter(CalculationLineResult.calculation_id == calc.id).first()

        run = InvestigationRun(
            id="run-custom-key",
            case_id="case-acme-101",
            calculation_id=calc.id,
            status="COMPLETED",
            evidence_version=1,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        db.add(run)

        finding = Finding(
            id="find-single-credit",
            case_id="case-acme-101",
            run_id=run.id,
            calculation_line_result_id=lr.id,
            finding_type="CONFIRMED_CALCULATION_DISCREPANCY",
            narrative="Overcharge",
            raw_ai_text="Overcharge",
            citation_validation_passed=True,
            consistency_check_passed=True,
            is_stale=False,
        )
        db.add(finding)

        review = FindingReview(
            finding_id=finding.id,
            reviewer="reviewer_demo",
            action="ACCEPT",
            note="OK",
        )
        db.add(review)

        opt = ResolutionOption(
            id="opt-single-credit",
            run_id=run.id,
            case_id="case-acme-101",
            option_type="RECOMMEND_CREDIT",
            description="Credit",
            calculation_line_result_id=lr.id,
        )
        db.add(opt)
        db.commit()

    # Credit 1 with custom key 1
    res1 = client.post(
        "/api/credits/approve",
        headers=REVIEWER_HEADERS,
        json={
            "case_id": "case-acme-101",
            "invoice_line_id": "line-api-calls",
            "reason_code": "RATE_ERROR",
            "finding_id": "find-single-credit",
            "resolution_option_id": "opt-single-credit",
            "requested_amount_cents": 500,
            "idempotency_key": "custom-key-alpha",
        },
    )
    assert res1.status_code == 201

    # Credit 2 with DIFFERENT custom key on same finding -> MUST fail with 409
    res2 = client.post(
        "/api/credits/approve",
        headers=REVIEWER_HEADERS,
        json={
            "case_id": "case-acme-101",
            "invoice_line_id": "line-api-calls",
            "reason_code": "RATE_ERROR",
            "finding_id": "find-single-credit",
            "resolution_option_id": "opt-single-credit",
            "requested_amount_cents": 500,
            "idempotency_key": "custom-key-beta",
        },
    )
    assert res2.status_code == 409
    assert "already approved for finding" in res2.text


def test_cross_case_line_id_isolation(seeded_client):
    """
    Credits on line-id in case A must not deduct from the credit cap of identical line-id in case B.
    """
    client, SessionLocal = seeded_client

    with SessionLocal() as db:
        # Create case B with an invoice line with the same ID as case-acme-101 ("line-api-calls")
        case_b = Case(
            id="case-beta-200",
            title="Isolated Dispute",
            customer_name="Beta Corp",
            disputed_amount_cents=5000,
            status="OPEN",
            evidence_version=1,
        )
        db.add(case_b)
        db.flush()

        line_b = InvoiceLine(
            case_id="case-beta-200",
            id="line-api-calls",
            description="Beta API Calls",
            original_amount_cents=5000,
        )
        db.add(line_b)

        calc_b = Calculation(
            id="calc-beta-1",
            case_id="case-beta-200",
            evidence_version=1,
            engine_status=EngineStatusDB.OK,
            total_original_billed_cents=5000,
            total_recalculated_cents=2500,
            total_difference_cents=-2500,
            result_hash="hash_beta",
        )
        db.add(calc_b)
        db.flush()

        lr_b = CalculationLineResult(
            calculation_id=calc_b.id,
            line_id="line-api-calls",
            result_id="res_beta_1",
            rule_id="rule_beta_1",
            original_amount_cents=5000,
            recalculated_amount_cents=2500,
            difference_cents=-2500,
            finding_type=FindingTypeDB.CONFIRMED_CALCULATION_DISCREPANCY,
            quantity_used=250,
            exempt_quantity=0,
            explanation="Beta calculation",
        )
        db.add(lr_b)

        # Record a prior credit on case-acme-101 for "line-api-calls"
        prior_credit = Credit(
            id="cred-acme-isolation",
            case_id="case-acme-101",
            invoice_line_id="line-api-calls",
            amount_cents=2000,
            idempotency_key="key-acme-iso",
            reason_code="PRIOR_DISPUTE",
            approved_by="reviewer",
        )
        db.add(prior_credit)
        db.commit()

    # Query cap for case-beta-200
    res = client.get(
        "/api/credits/case/case-beta-200/cap?invoice_line_id=line-api-calls",
        headers=REVIEWER_HEADERS,
    )
    assert res.status_code == 200
    data = res.json()
    # Prior credits in case B must be 0, not 2000 from case A!
    assert data["prior_credits_cents"] == 0
    assert data["remaining_cap_cents"] == 2500


def test_stale_finding_review_rejected_409(seeded_client):
    """
    Submitting a review on a stale finding must be rejected with HTTP 409 Conflict.
    """
    client, SessionLocal = seeded_client

    with SessionLocal() as db:
        run = InvestigationRun(
            id="run-stale-test",
            case_id="case-acme-101",
            status="COMPLETED",
            evidence_version=1,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        db.add(run)

        finding = Finding(
            id="find-stale-test",
            case_id="case-acme-101",
            run_id=run.id,
            finding_type="CONFIRMED_CALCULATION_DISCREPANCY",
            narrative="Old finding",
            is_stale=True,
            stale_reason="New telemetry evidence uploaded",
        )
        db.add(finding)
        db.commit()

    res = client.post(
        "/api/findings/find-stale-test/review",
        headers=REVIEWER_HEADERS,
        json={"action": "ACCEPT", "note": "Trying to review stale finding"},
    )
    assert res.status_code == 409
    assert "is stale" in res.text
    assert "Re-run the investigation" in res.text

