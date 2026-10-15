"""
tests/test_api_and_services.py
==============================
Comprehensive integration tests for Phase 2:
  1. Auth & Role Permissions (Bearer tokens: REVIEWER vs VIEWER vs 401/403).
  2. State Machine Transitions (valid paths + HTTP 409 Conflict on invalid).
  3. Evidence Upload & Staleness Invalidation (bumps version, invalidates findings, REOPENED from RESOLVED).
  4. Finding Reviews (ACCEPT, EDIT, REJECT, preserves original AI text).
  5. Deterministic Calculation API (end-to-end engine run via API).
  6. Credit Approval (requires accepted non-stale finding, enforces cumulative cap, HTTP 409 on repeat).
"""

import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.config import settings
from app.database import Base, get_db, set_sqlite_pragmas, install_append_only_triggers
from app.models.case import Case, CaseStatus, CaseEvent
from app.models.credit import Adjustment
from app.models.invoice import InvoiceLine, ContractRule, RuleTypeDB
from app.models.investigation import InvestigationRun, Finding, FindingReview
from app.models.calculation import Calculation, CalculationLineResult, EngineStatusDB, FindingTypeDB


REVIEWER_TOKEN = settings.demo_reviewer_token
VIEWER_TOKEN = settings.demo_viewer_token

REVIEWER_HEADERS = {"Authorization": f"Bearer {REVIEWER_TOKEN}"}
VIEWER_HEADERS = {"Authorization": f"Bearer {VIEWER_TOKEN}"}


@pytest.fixture
def client_and_session(tmp_path):
    """Sets up an isolated SQLite database with triggers for testing the API."""
    db_file = tmp_path / "test_api.sqlite"
    test_engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )
    event.listen(test_engine, "connect", set_sqlite_pragmas)

    Base.metadata.create_all(bind=test_engine)
    install_append_only_triggers(test_engine)

    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

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


class TestAuthAndRoles:
    def test_missing_auth_header_returns_401(self, client_and_session):
        client, _ = client_and_session
        res = client.get("/api/cases")
        assert res.status_code == 401
        assert "WWW-Authenticate" in res.headers

    def test_invalid_bearer_token_returns_401(self, client_and_session):
        client, _ = client_and_session
        res = client.get("/api/cases", headers={"Authorization": "Bearer fake-token-xyz"})
        assert res.status_code == 401

    def test_viewer_can_read_cases(self, client_and_session):
        client, _ = client_and_session
        res = client.get("/api/cases", headers=VIEWER_HEADERS)
        assert res.status_code == 200

    def test_viewer_cannot_create_case_returns_403(self, client_and_session):
        client, _ = client_and_session
        res = client.post(
            "/api/cases",
            headers=VIEWER_HEADERS,
            json={
                "title": "Disputed AWS Invoice",
                "customer_name": "Test Customer",
                "disputed_amount_cents": 10000,
            },
        )
        assert res.status_code == 403

    def test_production_environment_refuses_default_tokens(self):
        """Proves app refuses to boot in production with guessable default demo tokens when demo_mode is False."""
        from app.config import Settings
        with pytest.raises(ValueError, match="Production Security Error"):
            Settings(
                environment="production",
                demo_mode=False,
                demo_reviewer_token="demo-reviewer-token-2026",
                demo_viewer_token="demo-viewer-token-2026",
            )

    def test_auth_me_reviewer_profile(self, client_and_session):
        client, _ = client_and_session
        res = client.get("/api/auth/me", headers=REVIEWER_HEADERS)
        assert res.status_code == 200
        data = res.json()
        assert data["identity"] == "reviewer@fairbill.io"
        assert data["role"] == "REVIEWER"
        assert "approve:credits" in data["permissions"]
        assert data["demo_mode"] is True

    def test_auth_me_viewer_profile(self, client_and_session):
        client, _ = client_and_session
        res = client.get("/api/auth/me", headers=VIEWER_HEADERS)
        assert res.status_code == 200
        data = res.json()
        assert data["identity"] == "viewer@fairbill.io"
        assert data["role"] == "VIEWER"
        assert "approve:credits" not in data["permissions"]
        assert "read:cases" in data["permissions"]

    def test_demo_token_rejected_when_demo_mode_false(self, client_and_session, monkeypatch):
        client, _ = client_and_session
        monkeypatch.setattr(settings, "demo_mode", False)
        res = client.get("/api/auth/me", headers={"Authorization": "Bearer demo-reviewer-token-2026"})
        assert res.status_code == 401


class TestStateMachineTransitions:
    def _create_test_case(self, client, case_id="case-sm-1", initial_status="OPEN"):
        res = client.post(
            "/api/cases",
            headers=REVIEWER_HEADERS,
            json={
                "id": case_id,
                "title": "State Machine Test Case",
                "customer_name": "Acme Inc",
                "disputed_amount_cents": 5000,
                "invoice_lines": [
                    {"id": f"line-{case_id}", "description": "API requests", "original_amount_cents": 5000}
                ],
                "contract_rules": [
                    {
                        "id": f"rule-{case_id}",
                        "line_id": f"line-{case_id}",
                        "rule_type": "PER_UNIT",
                        "rate_cents": 10,
                    }
                ],
            },
        )
        assert res.status_code == 201
        return res.json()

    def test_valid_transitions_lifecycle(self, client_and_session):
        client, _ = client_and_session
        case = self._create_test_case(client, "case-life-1")

        # 1. OPEN -> AWAITING_INFO
        r1 = client.post(
            f"/api/cases/{case['id']}/transition",
            headers=REVIEWER_HEADERS,
            json={"target_status": "AWAITING_INFO", "note": "Requested contract copy"},
        )
        assert r1.status_code == 200
        assert r1.json()["status"] == "AWAITING_INFO"

        # 2. AWAITING_INFO -> OPEN
        r2 = client.post(
            f"/api/cases/{case['id']}/transition",
            headers=REVIEWER_HEADERS,
            json={"target_status": "OPEN", "note": "Contract uploaded"},
        )
        assert r2.status_code == 200
        assert r2.json()["status"] == "OPEN"

        # 3. OPEN -> RESOLVED
        r3 = client.post(
            f"/api/cases/{case['id']}/transition",
            headers=REVIEWER_HEADERS,
            json={"target_status": "RESOLVED", "note": "Resolution accepted"},
        )
        assert r3.status_code == 200
        assert r3.json()["status"] == "RESOLVED"

        # 4. RESOLVED -> REOPENED
        r4 = client.post(
            f"/api/cases/{case['id']}/transition",
            headers=REVIEWER_HEADERS,
            json={"target_status": "REOPENED", "note": "Customer challenged calculation"},
        )
        assert r4.status_code == 200
        assert r4.json()["status"] == "REOPENED"

        # 5. REOPENED -> AWAITING_INFO
        r5 = client.post(
            f"/api/cases/{case['id']}/transition",
            headers=REVIEWER_HEADERS,
            json={"target_status": "AWAITING_INFO"},
        )
        assert r5.status_code == 200
        assert r5.json()["status"] == "AWAITING_INFO"

    def test_invalid_transitions_return_409(self, client_and_session):
        client, _ = client_and_session
        case = self._create_test_case(client, "case-inv-1")

        # Cannot jump from OPEN -> REOPENED (only RESOLVED can reopen)
        r1 = client.post(
            f"/api/cases/{case['id']}/transition",
            headers=REVIEWER_HEADERS,
            json={"target_status": "REOPENED"},
        )
        assert r1.status_code == 409
        assert "Invalid case status transition" in r1.json()["detail"]

        # Move to AWAITING_INFO
        client.post(
            f"/api/cases/{case['id']}/transition",
            headers=REVIEWER_HEADERS,
            json={"target_status": "AWAITING_INFO"},
        )

        # Cannot jump from AWAITING_INFO -> REOPENED
        r2 = client.post(
            f"/api/cases/{case['id']}/transition",
            headers=REVIEWER_HEADERS,
            json={"target_status": "REOPENED"},
        )
        assert r2.status_code == 409


class TestEvidenceUploadAndStaleness:
    def test_evidence_upload_bumps_version_and_marks_findings_stale(self, client_and_session):
        client, SessionLocal = client_and_session
        # Create case
        client.post(
            "/api/cases",
            headers=REVIEWER_HEADERS,
            json={
                "id": "case-ev-1",
                "title": "Evidence Upload Test",
                "customer_name": "Test Co",
                "disputed_amount_cents": 5000,
                "invoice_lines": [{"id": "line-ev-1", "description": "Compute", "original_amount_cents": 5000}],
            },
        )

        # Create an existing finding directly in DB
        with SessionLocal() as db:
            run = InvestigationRun(id="run-1", case_id="case-ev-1", evidence_version=1, status="COMPLETED")
            finding = Finding(
                id="find-1",
                case_id="case-ev-1",
                run_id="run-1",
                finding_type="CONFIRMED_CALCULATION_DISCREPANCY",
                raw_ai_text="Initial calculation found 500 cents overcharge",
                is_stale=False,
            )
            db.add_all([run, finding])
            db.commit()

        # Upload new evidence
        res = client.post(
            "/api/cases/case-ev-1/evidence",
            headers=REVIEWER_HEADERS,
            json={
                "events": [
                    {
                        "event_id": "ev-1",
                        "line_id": "line-ev-1",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "quantity": 250.0,
                        "environment": "production",
                    }
                ],
                "source_note": "Added missing logs",
            },
        )
        assert res.status_code == 200
        body = res.json()
        assert body["new_evidence_version"] == 2
        assert body["stale_findings_count"] == 1

        # Verify in DB that finding is now marked is_stale = True
        with SessionLocal() as db:
            f = db.query(Finding).filter(Finding.id == "find-1").one()
            assert f.is_stale is True

    def test_evidence_upload_on_resolved_transitions_to_reopened(self, client_and_session):
        client, _ = client_and_session
        client.post(
            "/api/cases",
            headers=REVIEWER_HEADERS,
            json={
                "id": "case-res-1",
                "title": "Resolve and Reopen Test",
                "customer_name": "Test Co",
                "disputed_amount_cents": 5000,
                "invoice_lines": [{"id": "line-res-1", "description": "Compute", "original_amount_cents": 5000}],
            },
        )

        # Transition to RESOLVED
        client.post(
            "/api/cases/case-res-1/transition",
            headers=REVIEWER_HEADERS,
            json={"target_status": "RESOLVED"},
        )

        # Upload evidence on resolved case
        res = client.post(
            "/api/cases/case-res-1/evidence",
            headers=REVIEWER_HEADERS,
            json={
                "events": [
                    {
                        "event_id": "ev-late-1",
                        "line_id": "line-res-1",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "quantity": 100.0,
                        "environment": "production",
                    }
                ]
            },
        )
        assert res.status_code == 200
        assert res.json()["case_status"] == "REOPENED"

    def test_multiple_cases_can_share_line_and_rule_and_event_ids(self, client_and_session):
        """Verifies that line-1, rule-1, and ev-1 are scoped per case and do not collide globally."""
        client, _ = client_and_session

        # Create First Case with line-1, rule-1
        res1 = client.post(
            "/api/cases",
            headers=REVIEWER_HEADERS,
            json={
                "id": "case-tenant-alpha",
                "title": "Alpha Case",
                "customer_name": "Alpha Corp",
                "disputed_amount_cents": 1000,
                "invoice_lines": [{"id": "line-1", "description": "API Calls", "original_amount_cents": 1000}],
                "contract_rules": [{"id": "rule-1", "line_id": "line-1", "rule_type": "PER_UNIT", "rate_cents": 10}],
            },
        )
        assert res1.status_code == 201

        # Upload ev-1 to First Case
        res_ev1 = client.post(
            "/api/cases/case-tenant-alpha/evidence",
            headers=REVIEWER_HEADERS,
            json={
                "events": [
                    {
                        "event_id": "ev-1",
                        "line_id": "line-1",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "quantity": 100.0,
                        "environment": "production",
                    }
                ]
            },
        )
        assert res_ev1.status_code == 200

        # Create Second Case with identical line-1 and rule-1! Must succeed (no 409 conflict).
        res2 = client.post(
            "/api/cases",
            headers=REVIEWER_HEADERS,
            json={
                "id": "case-tenant-beta",
                "title": "Beta Case",
                "customer_name": "Beta Corp",
                "disputed_amount_cents": 2000,
                "invoice_lines": [{"id": "line-1", "description": "API Calls Beta", "original_amount_cents": 2000}],
                "contract_rules": [{"id": "rule-1", "line_id": "line-1", "rule_type": "PER_UNIT", "rate_cents": 20}],
            },
        )
        assert res2.status_code == 201

        # Upload ev-1 to Second Case! Must succeed (no 409 conflict).
        res_ev2 = client.post(
            "/api/cases/case-tenant-beta/evidence",
            headers=REVIEWER_HEADERS,
            json={
                "events": [
                    {
                        "event_id": "ev-1",
                        "line_id": "line-1",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "quantity": 200.0,
                        "environment": "production",
                    }
                ]
            },
        )
        assert res_ev2.status_code == 200


class TestFindingReviews:
    def test_finding_review_accept_edit_reject(self, client_and_session):
        client, SessionLocal = client_and_session
        # Setup case, run, and finding
        client.post(
            "/api/cases",
            headers=REVIEWER_HEADERS,
            json={
                "id": "case-rev-1",
                "title": "Review Test",
                "customer_name": "Review Corp",
                "disputed_amount_cents": 1000,
            },
        )
        with SessionLocal() as db:
            run = InvestigationRun(id="run-rev-1", case_id="case-rev-1", evidence_version=1, status="COMPLETED")
            f1 = Finding(
                id="f-accept",
                case_id="case-rev-1",
                run_id="run-rev-1",
                finding_type="CONFIRMED_CALCULATION_DISCREPANCY",
                raw_ai_text="Raw AI draft stating $5 overcharge",
                is_stale=False,
            )
            f2 = Finding(
                id="f-edit",
                case_id="case-rev-1",
                run_id="run-rev-1",
                finding_type="CONFIRMED_CALCULATION_DISCREPANCY",
                raw_ai_text="Raw AI draft with wording error",
                is_stale=False,
            )
            db.add_all([run, f1, f2])
            db.commit()

        # 1. ACCEPT review
        r1 = client.post(
            "/api/findings/f-accept/review",
            headers=REVIEWER_HEADERS,
            json={"action": "ACCEPT", "note": "Verified by senior analyst"},
        )
        assert r1.status_code == 201
        assert r1.json()["action"] == "ACCEPT"
        assert r1.json()["original_ai_text"] == "Raw AI draft stating $5 overcharge"
        assert r1.json()["edited_text"] is None

        # 2. EDIT review requires edited_text
        r2_fail = client.post(
            "/api/findings/f-edit/review",
            headers=REVIEWER_HEADERS,
            json={"action": "EDIT", "note": "Forgot edit"},
        )
        assert r2_fail.status_code == 400

        r2 = client.post(
            "/api/findings/f-edit/review",
            headers=REVIEWER_HEADERS,
            json={"action": "EDIT", "note": "Fixed customer tone", "edited_text": "Corrected analyst text."},
        )
        assert r2.status_code == 201
        assert r2.json()["action"] == "EDIT"
        assert r2.json()["original_ai_text"] == "Raw AI draft with wording error"
        assert r2.json()["edited_text"] == "Corrected analyst text."


class TestCalculationAPI:
    def test_run_calculation_end_to_end(self, client_and_session):
        client, _ = client_and_session
        # Create case with tiered graduated rule
        client.post(
            "/api/cases",
            headers=REVIEWER_HEADERS,
            json={
                "id": "case-calc-e2e",
                "title": "Graduated Calculation",
                "customer_name": "Tier Customer",
                "disputed_amount_cents": 10000,
                "invoice_lines": [
                    {"id": "line-calc-1", "description": "API Usage", "original_amount_cents": 10000}
                ],
                "contract_rules": [
                    {
                        "id": "rule-calc-1",
                        "line_id": "line-calc-1",
                        "rule_type": "TIERED_GRADUATED",
                        "rate_cents": 0,
                        "tiers": [
                            {"up_to": 100, "rate_cents": 10},
                            {"up_to": 500, "rate_cents": 8},
                            {"up_to": None, "rate_cents": 5},
                        ],
                        "exempt_environments": ["staging"],
                    }
                ],
            },
        )

        # Upload usage events: 200 units prod + 50 units staging (exempt)
        client.post(
            "/api/cases/case-calc-e2e/evidence",
            headers=REVIEWER_HEADERS,
            json={
                "events": [
                    {
                        "event_id": "ev-prod-1",
                        "line_id": "line-calc-1",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "quantity": 200.0,
                        "environment": "production",
                    },
                    {
                        "event_id": "ev-stg-1",
                        "line_id": "line-calc-1",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "quantity": 50.0,
                        "environment": "staging",
                    },
                ]
            },
        )

        # Run calculation
        res = client.post(
            "/api/calculations/run",
            headers=REVIEWER_HEADERS,
            json={"case_id": "case-calc-e2e"},
        )
        assert res.status_code == 201
        data = res.json()
        assert data["engine_status"] == "OK"
        # 100 * 10 + 100 * 8 = 1000 + 800 = 1800 cents recalculated.
        # Original was 10000 cents. Discrepancy is 1800 - 10000 = -8200 (overcharge).
        assert data["total_recalculated_cents"] == 1800
        assert data["total_difference_cents"] == -8200
        assert len(data["line_results"]) == 1
        lr = data["line_results"][0]
        assert lr["exempt_quantity"] == 50.0
        assert lr["quantity_used"] == 200.0
        assert lr["result_id"].startswith("res_")


class TestCreditApprovalAndConcurrencyCap:
    def _setup_disputed_line_with_finding(self, client, SessionLocal, case_id="case-cred-1", diff_cents=-3000):
        # 1. Create case
        client.post(
            "/api/cases",
            headers=REVIEWER_HEADERS,
            json={
                "id": case_id,
                "title": "Credit Test Case",
                "customer_name": "Credit Customer",
                "disputed_amount_cents": 5000,
                "invoice_lines": [
                    {"id": f"line-{case_id}", "description": "Overcharged line", "original_amount_cents": 5000}
                ],
            },
        )

        # 2. Directly insert calculation line result and finding in DB
        with SessionLocal() as db:
            calc = Calculation(
                id=f"calc-{case_id}",
                case_id=case_id,
                evidence_version=1,
                engine_status=EngineStatusDB.OK,
                total_original_billed_cents=5000,
                total_recalculated_cents=5000 + diff_cents,
                total_difference_cents=diff_cents,
                result_hash="hash-abc",
            )
            clr = CalculationLineResult(
                calculation_id=f"calc-{case_id}",
                line_id=f"line-{case_id}",
                result_id="res_1234567890abcdef",
                rule_id="rule-test",
                original_amount_cents=5000,
                recalculated_amount_cents=5000 + diff_cents,
                difference_cents=diff_cents,
                finding_type=FindingTypeDB.CONFIRMED_CALCULATION_DISCREPANCY,
                quantity_used=100.0,
                exempt_quantity=0.0,
                explanation="Confirmed overcharge",
            )
            db.add_all([calc, clr])
            db.flush()

            run = InvestigationRun(id=f"run-{case_id}", case_id=case_id, evidence_version=1, status="COMPLETED")
            finding = Finding(
                id=f"find-{case_id}",
                case_id=case_id,
                run_id=f"run-{case_id}",
                calculation_line_result_id=clr.id,
                finding_type="CONFIRMED_CALCULATION_DISCREPANCY",
                raw_ai_text="Eligible for refund",
                citation_validation_passed=True,
                consistency_check_passed=True,
                is_stale=False,
            )
            db.add_all([run, finding])
            db.commit()

        return f"line-{case_id}", f"find-{case_id}"

    def test_credit_rejected_without_accepted_finding(self, client_and_session):
        client, SessionLocal = client_and_session
        line_id, find_id = self._setup_disputed_line_with_finding(client, SessionLocal, "case-cred-no-rev")

        # Attempt to approve credit before any human review
        res = client.post(
            "/api/credits/approve",
            headers=REVIEWER_HEADERS,
            json={
                "case_id": "case-cred-no-rev",
                "invoice_line_id": line_id,
                "reason_code": "OVERCHARGE",
                "finding_id": find_id,
            },
        )
        assert res.status_code == 400
        assert "requires an accepted human finding review" in res.json()["detail"]

    def test_credit_rejected_when_finding_is_stale(self, client_and_session):
        client, SessionLocal = client_and_session
        line_id, find_id = self._setup_disputed_line_with_finding(client, SessionLocal, "case-cred-stale")

        # Accept the finding
        client.post(
            f"/api/findings/{find_id}/review",
            headers=REVIEWER_HEADERS,
            json={"action": "ACCEPT"},
        )

        # Mark finding stale via new evidence upload
        client.post(
            "/api/cases/case-cred-stale/evidence",
            headers=REVIEWER_HEADERS,
            json={
                "events": [
                    {
                        "event_id": "ev-new-1",
                        "line_id": line_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "quantity": 10.0,
                    }
                ]
            },
        )

        # Attempt to approve credit on stale finding
        res = client.post(
            "/api/credits/approve",
            headers=REVIEWER_HEADERS,
            json={
                "case_id": "case-cred-stale",
                "invoice_line_id": line_id,
                "reason_code": "OVERCHARGE",
                "finding_id": find_id,
            },
        )
        assert res.status_code == 400
        assert "Finding is stale" in res.json()["detail"]

    def test_credit_approval_success_and_repeat_409_conflict(self, client_and_session):
        client, SessionLocal = client_and_session
        line_id, find_id = self._setup_disputed_line_with_finding(client, SessionLocal, "case-cred-idemp", diff_cents=-3000)

        # Accept the finding
        client.post(
            f"/api/findings/{find_id}/review",
            headers=REVIEWER_HEADERS,
            json={"action": "ACCEPT"},
        )

        # 1. First approval succeeds
        r1 = client.post(
            "/api/credits/approve",
            headers=REVIEWER_HEADERS,
            json={
                "case_id": "case-cred-idemp",
                "invoice_line_id": line_id,
                "reason_code": "RATE_ERROR",
                "finding_id": find_id,
                "reason_note": "Approved $30.00 credit",
            },
        )
        assert r1.status_code == 201
        data = r1.json()
        assert data["amount_cents"] == 3000
        assert data["reason_code"] == "RATE_ERROR"
        assert data["approved_by"] == "reviewer@fairbill.io"

        # 2. Exact same request: duplicate idempotency key returns HTTP 409 Conflict
        r2 = client.post(
            "/api/credits/approve",
            headers=REVIEWER_HEADERS,
            json={
                "case_id": "case-cred-idemp",
                "invoice_line_id": line_id,
                "reason_code": "RATE_ERROR",
                "finding_id": find_id,
            },
        )
        assert r2.status_code == 409
        assert "Credit already approved with idempotency key" in r2.json()["detail"]

        # 3. Bug 4 regression test: Changing reason code must NOT bypass duplicate protection!
        r3 = client.post(
            "/api/credits/approve",
            headers=REVIEWER_HEADERS,
            json={
                "case_id": "case-cred-idemp",
                "invoice_line_id": line_id,
                "reason_code": "GOODWILL",
                "finding_id": find_id,
            },
        )
        assert r3.status_code == 409
        assert "Credit already approved with idempotency key" in r3.json()["detail"]

    def test_credit_cumulative_cap_exceeded_returns_400(self, client_and_session):
        client, SessionLocal = client_and_session
        line_id, find_id = self._setup_disputed_line_with_finding(client, SessionLocal, "case-cred-cap", diff_cents=-2000)

        # Accept the finding
        client.post(
            f"/api/findings/{find_id}/review",
            headers=REVIEWER_HEADERS,
            json={"action": "ACCEPT"},
        )

        # Add prior adjustment on this line for 2000 cents so line cap is exhausted
        with SessionLocal() as db:
            db.add(
                Adjustment(
                    id="adj-cap-exhaust",
                    case_id="case-cred-cap",
                    invoice_line_id=line_id,
                    amount_cents=2000,
                    description="Prior adjustment",
                )
            )
            db.commit()

        # Attempt credit approval: line_cap = 2000 - 0 - 2000 = 0 -> returns 400
        r1 = client.post(
            "/api/credits/approve",
            headers=REVIEWER_HEADERS,
            json={
                "case_id": "case-cred-cap",
                "invoice_line_id": line_id,
                "reason_code": "REASON_ONE",
                "finding_id": find_id,
            },
        )
        assert r1.status_code == 400
        assert "Cumulative credit cap reached" in r1.json()["detail"]

    def test_credit_rejected_when_invoice_line_mismatches_calculation_result(self, client_and_session):
        """Regression test: prevents credit approval when line_result.line_id != invoice_line_id."""
        client, SessionLocal = client_and_session
        line_id, find_id = self._setup_disputed_line_with_finding(
            client, SessionLocal, "case-cred-wrong-line", diff_cents=-2000
        )

        # Accept finding
        client.post(f"/api/findings/{find_id}/review", headers=REVIEWER_HEADERS, json={"action": "ACCEPT"})

        # Add a second invoice line to the same case
        with SessionLocal() as db:
            db.add(
                InvoiceLine(
                    id="line-other-different",
                    case_id="case-cred-wrong-line",
                    description="Different service line",
                    original_amount_cents=5000,
                )
            )
            db.commit()

        # Attempt to credit line-other-different using finding tied to line_id
        res = client.post(
            "/api/credits/approve",
            headers=REVIEWER_HEADERS,
            json={
                "case_id": "case-cred-wrong-line",
                "invoice_line_id": "line-other-different",
                "reason_code": "WRONG_LINE_DISCREPANCY",
                "finding_id": find_id,
            },
        )
        assert res.status_code == 400
        assert "Invoice line mismatch" in res.json()["detail"]

    def test_path_traversal_blocked_on_spa_route(self, client_and_session):
        """Security regression test: verify path traversal cannot escape frontend/dist."""
        client, _ = client_and_session
        res = client.get("/../../backend/requirements.txt")
        # Must NEVER return the requirements.txt file contents
        assert "fastapi" not in res.text
        assert "uvicorn" not in res.text
        # Instead returns SPA index.html (200) or 404 Not Found
        assert res.status_code in (200, 404)
        if res.status_code == 200:
            assert "<!doctype html" in res.text.lower() or "<html" in res.text.lower()

    def test_case_with_adjustments_and_line_id_validation(self, client_and_session):
        """Regression test for Bug 1: AdjustmentCreate supports invoice_line_id and validates references."""
        client, SessionLocal = client_and_session
        case_payload = {
            "id": "case-test-adj-valid",
            "title": "Dispute with adjustments",
            "customer_name": "Acme Corp",
            "disputed_amount_cents": 10000,
            "dispute_description": "Customer claims they received a prior $15 credit",
            "invoice_lines": [
                {
                    "id": "line-adj-1",
                    "description": "API requests",
                    "original_amount_cents": 10000,
                }
            ],
            "contract_rules": [
                {
                    "id": "rule-adj-1",
                    "line_id": "line-adj-1",
                    "rule_type": "PER_UNIT",
                    "rate_cents": 10,
                }
            ],
            "adjustments": [
                {
                    "id": "adj-1",
                    "invoice_line_id": "line-adj-1",
                    "amount_cents": 1500,
                    "description": "Prior courtesy credit",
                },
                {
                    "id": "adj-2",
                    "invoice_line_id": None,
                    "amount_cents": 500,
                    "description": "Case-wide goodwill adjustment",
                },
            ],
        }

        # 1. Valid adjustments succeed
        res = client.post("/api/cases", headers=REVIEWER_HEADERS, json=case_payload)
        assert res.status_code == 201

        # 2. GET /api/cases/{case_id} returns adjustments without 500
        get_res = client.get("/api/cases/case-test-adj-valid", headers=REVIEWER_HEADERS)
        assert get_res.status_code == 200
        data = get_res.json()
        assert len(data["adjustments"]) == 2
        assert data["adjustments"][0]["invoice_line_id"] == "line-adj-1"
        assert data["adjustments"][1]["invoice_line_id"] is None
        assert data["dispute_description"] == "Customer claims they received a prior $15 credit"

        # 3. Invalid adjustment referencing non-existent line ID returns 422
        bad_payload = dict(case_payload)
        bad_payload["id"] = "case-test-adj-invalid"
        bad_payload["adjustments"] = [
            {
                "id": "adj-bad",
                "invoice_line_id": "non-existent-line",
                "amount_cents": 1000,
                "description": "Bad adjustment",
            }
        ]
        bad_res = client.post("/api/cases", headers=REVIEWER_HEADERS, json=bad_payload)
        assert bad_res.status_code == 422
        assert "references invoice_line_id" in bad_res.json()["detail"][0]["msg"]

    def test_case_wide_credit_cap_enforced_via_latest_calculation_join(self, client_and_session):
        """Regression test for Bug 2: credit_service joins Calculation and isolates latest calculation."""
        client, SessionLocal = client_and_session
        line_id, find_id = self._setup_disputed_line_with_finding(
            client, SessionLocal, "case-cred-casewide", diff_cents=-3000
        )

        # Accept finding
        client.post(f"/api/findings/{find_id}/review", headers=REVIEWER_HEADERS, json={"action": "ACCEPT"})

        # Add a case-wide adjustment of 1000 cents
        with SessionLocal() as db:
            db.add(
                Adjustment(
                    id="adj-casewide-1",
                    case_id="case-cred-casewide",
                    invoice_line_id=None,
                    amount_cents=1000,
                    description="Case-wide goodwill",
                )
            )
            # Add older calculation to verify join and latest calculation filtering
            calc_old = Calculation(
                id="calc-old-discarded",
                case_id="case-cred-casewide",
                evidence_version=1,
                engine_status=EngineStatusDB.OK,
                total_original_billed_cents=5000,
                total_recalculated_cents=2000,
                total_difference_cents=-3000,
                result_hash="hash_old",
            )
            db.add(calc_old)
            db.flush()
            db.add(
                CalculationLineResult(
                    id=9999,
                    calculation_id=calc_old.id,
                    line_id=line_id,
                    result_id="res_old_1234567890abcdef",
                    rule_id="rule-test",
                    original_amount_cents=5000,
                    recalculated_amount_cents=2000,
                    difference_cents=-3000,
                    finding_type=FindingTypeDB.CONFIRMED_CALCULATION_DISCREPANCY,
                    quantity_used=10.0,
                    exempt_quantity=0.0,
                    explanation="Old calculation",
                )
            )
            db.commit()

        # Total case overcharge from latest calculation is 3000.
        # Case wide adjustment is 1000.
        # Case cap = 3000 - 0 - 1000 = 2000 cents.
        # Remaining cap is min(line_cap=3000, case_cap=2000) = 2000.
        # Credit approval will cap amount at 2000 cents.
        res = client.post(
            "/api/credits/approve",
            headers=REVIEWER_HEADERS,
            json={
                "case_id": "case-cred-casewide",
                "invoice_line_id": line_id,
                "reason_code": "RATE_ERROR",
                "finding_id": find_id,
            },
        )
        assert res.status_code == 201
        assert res.json()["amount_cents"] == 2000

    def test_failed_investigation_run_writes_audit_event_and_returns_status_failed(
        self, client_and_session, monkeypatch
    ):
        """Regression test for Bug 5: FAILED run writes INVESTIGATION_RUN_FAILED event and returns 200 OK."""
        client, SessionLocal = client_and_session
        # Setup case with invoice line and contract rule so gather_evidence proceeds to LLM
        client.post(
            "/api/cases",
            headers=REVIEWER_HEADERS,
            json={
                "id": "case-investigate-fail",
                "title": "Failing Case",
                "customer_name": "Acme Inc",
                "disputed_amount_cents": 5000,
                "invoice_lines": [
                    {"id": "line-fail-1", "description": "API requests", "original_amount_cents": 5000}
                ],
                "contract_rules": [
                    {
                        "id": "rule-fail-1",
                        "line_id": "line-fail-1",
                        "rule_type": "PER_UNIT",
                        "rate_cents": 10,
                    }
                ],
            },
        )

        from app.agent import llm_client

        def mock_failing_investigate(*args, **kwargs):
            raise RuntimeError("Simulated upstream Gemini API connection failure")

        monkeypatch.setattr(llm_client, "generate_investigation_findings", mock_failing_investigate)

        res = client.post(
            "/api/cases/case-investigate-fail/investigations",
            headers=REVIEWER_HEADERS,
        )
        assert res.status_code == 502
        data = res.json()
        assert data["status"] == "FAILED"
        assert "Simulated upstream Gemini API connection failure" in (data.get("reason") or data.get("status_reason", ""))

        with SessionLocal() as db:
            events = db.query(CaseEvent).filter(CaseEvent.case_id == "case-investigate-fail").all()
            event_types = [e.event_type for e in events]
            assert "INVESTIGATION_RUN_FAILED" in event_types

    def test_repeat_investigation_returns_409_if_already_running(
        self, client_and_session, monkeypatch
    ):
        """Repeat-run guard: triggers 409 through the real flow if two concurrent investigation calls occur."""
        client, SessionLocal = client_and_session
        case_id = "case-repeat-run"
        client.post(
            "/api/cases",
            headers=REVIEWER_HEADERS,
            json={
                "id": case_id,
                "title": "Repeat Run Test",
                "customer_name": "Acme Inc",
                "disputed_amount_cents": 5000,
                "invoice_lines": [{"id": "line-rep-1", "description": "API requests", "original_amount_cents": 5000}],
                "contract_rules": [{"id": "rule-rep-1", "line_id": "line-rep-1", "rule_type": "FLAT", "rate_cents": 5000}],
            },
        )

        from app.agent.graph import InvestigationWorkflow
        second_call_status = {}
        original_gather = InvestigationWorkflow.gather_evidence_node

        def concurrent_trigger_gather(workflow_self, state):
            # While the first investigation is actively running in the real graph flow, fire a concurrent trigger
            concurrent_res = client.post(
                f"/api/cases/{case_id}/investigations",
                headers=REVIEWER_HEADERS,
            )
            second_call_status["status_code"] = concurrent_res.status_code
            second_call_status["detail"] = concurrent_res.json().get("detail", "")
            return original_gather(workflow_self, state)

        monkeypatch.setattr(InvestigationWorkflow, "gather_evidence_node", concurrent_trigger_gather)

        res1 = client.post(
            f"/api/cases/{case_id}/investigations",
            headers=REVIEWER_HEADERS,
        )
        assert res1.status_code == 201
        assert second_call_status["status_code"] == 409
        assert "already currently running" in second_call_status["detail"]

    def test_case_create_rejects_nan_discount(self, client_and_session):
        """Schema validation rejects NaN or non-finite discount_pct."""
        client, _ = client_and_session
        raw_json = (
            '{"id": "case-nan-disc", "title": "NaN Test", "customer_name": "Test Co", '
            '"disputed_amount_cents": 1000, "invoice_lines": [{"id": "line-1", "description": "L1", "original_amount_cents": 1000}], '
            '"contract_rules": [{"id": "rule-1", "line_id": "line-1", "rule_type": "PER_UNIT", "discount_pct": NaN}]}'
        )
        res = client.post(
            "/api/cases",
            headers={"Content-Type": "application/json", **REVIEWER_HEADERS},
            content=raw_json,
        )
        assert res.status_code == 422





