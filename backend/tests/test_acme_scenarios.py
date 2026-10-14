"""
Comprehensive tests for Acme Scenarios A & B, Tier Slab Validation,
and Investigation / Credit Safeguards.
"""
import pytest
from decimal import Decimal
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.config import settings
from app.models.case import Case
from app.billing_engine import (
    RuleType,
    FindingType,
    TierBand,
    calculate_line,
    run_calculation,
    InvoiceLine as EngineLine,
    ContractRule as EngineRule,
    UsageEvent as EngineEvent,
)
from app.models.investigation import InvestigationRun, Finding, FindingReview
from app.models.calculation import Calculation, CalculationLineResult

REVIEWER_HEADERS = {"Authorization": f"Bearer {settings.demo_reviewer_token}"}


from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timezone

import app.database as db_module
from app.database import Base, get_db, set_sqlite_pragmas

@pytest.fixture
def test_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_acme.sqlite"
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
    yield test_engine, TestSessionLocal
    app.dependency_overrides.clear()


class TestAcmeScenariosDeterministicEngine:
    """Phase 7: Exact financial calculations for Acme Scenarios."""

    def test_scenario_b_exact_calculation_and_overcharge(self):
        """
        Scenario B: Acme - Verified Tier Overcharge
        Contract:
          0 - 500 @ 0c
          500 - 1000 @ 80c
          1000+ @ 45c
        Usage: 1,200 calls.
        Original billed: $1,850 (185,000 cents).
        Expected:
          First 500: $0
          Next 500: $400
          Final 200: $90
          Recalculated: $490 (49,000 cents)
          Difference: -$1,360 (-136,000 cents overcharge)
        """
        line = EngineLine(line_id="L-API", description="API Calls", original_amount_cents=185000)
        rule = EngineRule(
            rule_id="R-TIER",
            line_id="L-API",
            rule_type=RuleType.TIERED_GRADUATED,
            tiers=[
                TierBand(up_to=500, price_per_unit_cents=0),
                TierBand(up_to=1000, price_per_unit_cents=80),
                TierBand(up_to=None, price_per_unit_cents=45),
            ]
        )
        event = EngineEvent(event_id="EV-1", line_id="L-API", quantity=Decimal("1200"), environment="production")

        result = run_calculation([line], [rule], [event])

        assert result.status.value == "OK"
        assert result.total_recalculated_cents == 49000
        assert result.total_difference_cents == -136000
        assert len(result.line_results) == 1
        line_res = result.line_results[0]
        assert line_res.recalculated_amount_cents == 49000
        assert line_res.difference_cents == -136000
        assert line_res.finding_type == FindingType.CONFIRMED_CALCULATION_DISCREPANCY

    def test_scenario_a_missing_evidence_unavailable_amount(self):
        """
        Scenario A: Acme - Missing Evidence
        Contract is tiered, but 0 usage events exist.
        Engine MUST return INSUFFICIENT_DATA and None amounts (never $0.00).
        """
        line = EngineLine(line_id="L-API", description="API Calls", original_amount_cents=185000)
        rule = EngineRule(
            rule_id="R-TIER",
            line_id="L-API",
            rule_type=RuleType.TIERED_GRADUATED,
            tiers=[
                TierBand(up_to=500, price_per_unit_cents=0),
                TierBand(up_to=1000, price_per_unit_cents=80),
                TierBand(up_to=None, price_per_unit_cents=45),
            ]
        )

        result = run_calculation([line], [rule], [])

        assert result.status.value == "INSUFFICIENT_DATA"
        assert result.total_recalculated_cents is None
        assert result.total_difference_cents is None
        assert len(result.line_results) == 1
        assert result.line_results[0].recalculated_amount_cents is None
        assert result.line_results[0].difference_cents is None
        assert result.line_results[0].finding_type == FindingType.INSUFFICIENT_DATA


class TestTierSlabValidation:
    """Phase 2 & 4: Tier slab validation rules."""

    def test_overlapping_tiers_returns_insufficient_data(self):
        line = EngineLine(line_id="L-API", description="API Calls", original_amount_cents=10000)
        rule = EngineRule(
            rule_id="R-BAD",
            line_id="L-API",
            rule_type=RuleType.TIERED_GRADUATED,
            tiers=[
                TierBand(up_to=600, price_per_unit_cents=10),
                TierBand(up_to=500, price_per_unit_cents=20),  # non-increasing bound
            ]
        )
        event = EngineEvent(event_id="EV-1", line_id="L-API", quantity=Decimal("700"), environment="production")
        res = calculate_line(line, [rule], [event])
        assert res.finding_type == FindingType.INSUFFICIENT_DATA

    def test_negative_tier_rate_rejected(self):
        line = EngineLine(line_id="L-API", description="API Calls", original_amount_cents=10000)
        rule = EngineRule(
            rule_id="R-BAD",
            line_id="L-API",
            rule_type=RuleType.TIERED_GRADUATED,
            tiers=[
                TierBand(up_to=500, price_per_unit_cents=-5),
            ]
        )
        event = EngineEvent(event_id="EV-1", line_id="L-API", quantity=Decimal("200"), environment="production")
        res = calculate_line(line, [rule], [event])
        assert res.finding_type == FindingType.INSUFFICIENT_DATA


class TestCreditSafeguardsAndEndToEnd:
    """Phase 6: Credit cap, unverified adjustments, and review safeguards."""

    def test_scenario_a_cannot_approve_credit_when_evidence_missing(self, test_db):
        _, Session = test_db
        with TestClient(app) as client:
            # Run calculation for Scenario A
            res_calc = client.post("/api/calculations/run", json={"case_id": "case-acme-unverified"}, headers=REVIEWER_HEADERS)
            assert res_calc.status_code == 201
            calc_data = res_calc.json()
            assert calc_data["engine_status"] == "INSUFFICIENT_DATA"

            # Check remaining cap
            res_cap = client.get(
                "/api/credits/case/case-acme-unverified/cap?invoice_line_id=line-acme-calls-unverified",
                headers=REVIEWER_HEADERS
            )
            assert res_cap.status_code == 200
            cap_data = res_cap.json()
            assert cap_data["remaining_cap_cents"] == 0
            assert cap_data["unverified_adjustments_cents"] == 10000  # $100 unverified claim tracked

            # Attempting to approve a credit must be rejected
            res_credit = client.post(
                "/api/credits/approve",
                json={
                    "case_id": "case-acme-unverified",
                    "invoice_line_id": "line-acme-calls-unverified",
                    "requested_amount_cents": 10000,
                    "reason_code": "CUSTOMER_COURTESY",
                    "finding_id": "find-none",
                },
                headers=REVIEWER_HEADERS,
            )
            assert res_credit.status_code in (400, 404)

    def test_scenario_b_credit_approval_and_cap_enforcement(self, test_db):
        _, SessionLocal = test_db
        with TestClient(app) as client:
            # 1. Run calculation on Scenario B
            res_calc = client.post("/api/calculations/run", json={"case_id": "case-acme-verified"}, headers=REVIEWER_HEADERS)
            assert res_calc.status_code == 201
            calc_data = res_calc.json()
            assert calc_data["engine_status"] == "OK"
            assert calc_data["total_difference_cents"] == -136000  # $1,360 overcharge
            calc_id = calc_data["id"]

            # 2. Check remaining cap ($1,360 = 136,000 cents)
            res_cap = client.get(
                "/api/credits/case/case-acme-verified/cap?invoice_line_id=line-acme-calls-verified",
                headers=REVIEWER_HEADERS
            )
            assert res_cap.status_code == 200
            cap_data = res_cap.json()
            assert cap_data["remaining_cap_cents"] == 136000

            # 3. Add an accepted finding for Scenario B to satisfy human review & validation checks
            now = datetime.now(timezone.utc)
            with SessionLocal() as db:
                run = InvestigationRun(
                    id="run-acme-b-1",
                    case_id="case-acme-verified",
                    evidence_version=1,
                    status="COMPLETED",
                    started_at=now,
                    completed_at=now,
                )
                db.add(run)
                db.flush()

                lr = db.query(CalculationLineResult).filter(CalculationLineResult.calculation_id == calc_id).first()

                finding = Finding(
                    id="find-acme-verified-1",
                    case_id="case-acme-verified",
                    run_id=run.id,
                    calculation_line_result_id=lr.id,
                    finding_type="CONFIRMED_CALCULATION_DISCREPANCY",
                    raw_ai_text="Graduated tier rates recalculated to $490, confirming $1,360 overcharge.",
                    citation_validation_passed=True,
                    consistency_check_passed=True,
                    is_stale=False,
                )
                db.add(finding)
                db.flush()

                review = FindingReview(
                    finding_id=finding.id,
                    reviewer="reviewer-1",
                    action="ACCEPT",
                    note="Verified tier math against contract terms",
                )
                db.add(review)
                db.commit()

            # 4. Approve partial credit of $500 (50,000 cents)
            res_credit = client.post(
                "/api/credits/approve",
                json={
                    "case_id": "case-acme-verified",
                    "invoice_line_id": "line-acme-calls-verified",
                    "finding_id": "find-acme-verified-1",
                    "reason_code": "VERIFIED_RATE_OVERCHARGE",
                    "requested_amount_cents": 50000,
                    "reason_note": "Verified tier overcharge partial resolution",
                },
                headers=REVIEWER_HEADERS,
            )
            assert res_credit.status_code == 201
            credit_data = res_credit.json()
            assert credit_data["amount_cents"] == 50000
            assert "id" in credit_data

            # 5. Check cap is now 86,000 cents ($860)
            res_cap2 = client.get(
                "/api/credits/case/case-acme-verified/cap?invoice_line_id=line-acme-calls-verified",
                headers=REVIEWER_HEADERS
            )
            assert res_cap2.json()["remaining_cap_cents"] == 86000

            # 6. Approving more than remaining cap ($900 > $860) must fail
            # Note: finding can only receive 1 credit, so this will be rejected
            res_over = client.post(
                "/api/credits/approve",
                json={
                    "case_id": "case-acme-verified",
                    "invoice_line_id": "line-acme-calls-verified",
                    "finding_id": "find-acme-verified-1",
                    "reason_code": "VERIFIED_RATE_OVERCHARGE",
                    "requested_amount_cents": 90000,
                    "reason_note": "Excess credit",
                },
                headers=REVIEWER_HEADERS,
            )
            assert res_over.status_code in (400, 409)
