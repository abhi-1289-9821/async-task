"""
tests/test_seven_cases.py
=========================
Comprehensive integration test for the 7 FairBill billing dispute cases:
  Case 1 (Acme A): Missing evidence, unverified usage -> INSUFFICIENT_DATA
  Case 2 (Acme B): Verified graduated-tier overcharge -> $675 recalc, -$275 diff
  Case 3 (Bravo): Conflicting contract amendments at tier threshold -> AMBIGUOUS, two interpretations
  Case 4 (Delta): Fixed fee, duplicate fee allegation, prior adjustment accounting -> remaining cap $80
  Case 5 (Echo): Included units allowance & exempt environment removal -> $50 recalc, -$200 diff
  Case 6 (Foxtrot): Percentage discount on eligible base & prompt injection resilience -> $2000 recalc, -$300 diff
  Case 7 (Golf): Minimum commitment floor & lower actual usage -> $500 recalc, -$100 diff
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.config import settings
from app.database import Base, get_db, set_sqlite_pragmas
import app.database as db_module
from app.seed import seed_demo_cases

REVIEWER_HEADERS = {"Authorization": f"Bearer {settings.demo_reviewer_token}"}


@pytest.fixture
def clean_db(tmp_path, monkeypatch):
    """Creates a temporary SQLite DB seeded with all demo cases."""
    db_file = tmp_path / "test_seven_cases.sqlite"
    test_engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )
    event.listen(test_engine, "connect", set_sqlite_pragmas)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    monkeypatch.setattr(db_module, "engine", test_engine)
    monkeypatch.setattr(db_module, "SessionLocal", TestSessionLocal)

    Base.metadata.create_all(bind=test_engine)
    db = TestSessionLocal()
    seed_demo_cases(db, force=True)
    db.close()

    def override_get_db():
        db_s = TestSessionLocal()
        try:
            yield db_s
        finally:
            db_s.close()

    app.dependency_overrides[get_db] = override_get_db
    yield test_engine, TestSessionLocal
    app.dependency_overrides.clear()


def test_case_1_acme_a_missing_evidence(clean_db):
    """Case 1: Engine refuses to calculate final amount from customer claims alone."""
    with TestClient(app) as client:
        # Check case exists
        c_res = client.get("/api/cases/case-1-acme-a", headers=REVIEWER_HEADERS)
        assert c_res.status_code == 200
        case_data = c_res.json()
        assert case_data["customer_name"] == "Acme A"
        assert case_data["claimed_usage_quantity"] == 1200.0

        # Run calculation
        res = client.post("/api/calculations/run", json={"case_id": "case-1-acme-a"}, headers=REVIEWER_HEADERS)
        assert res.status_code == 201
        calc = res.json()
        assert calc["engine_status"] == "INSUFFICIENT_DATA"
        assert calc["total_recalculated_cents"] is None
        assert calc["total_difference_cents"] is None

        # Line result check
        line_res = calc["line_results"][0]
        assert line_res["finding_type"] == "INSUFFICIENT_DATA"
        assert line_res["recalculated_amount_cents"] is None


def test_case_2_acme_b_graduated_tiers(clean_db):
    """Case 2: Correct multi-tier graduated calculation with exempt staging usage."""
    with TestClient(app) as client:
        res = client.post("/api/calculations/run", json={"case_id": "case-2-acme-b"}, headers=REVIEWER_HEADERS)
        assert res.status_code == 201
        calc = res.json()
        assert calc["engine_status"] == "OK"
        # 500 @ 80¢ = $400, 500 @ 45¢ = $225, 200 @ 25¢ = $50 -> Total $675.00
        assert calc["total_recalculated_cents"] == 67500
        assert calc["total_original_billed_cents"] == 95000
        assert calc["total_difference_cents"] == -27500  # $275.00 overcharge

        line_res = calc["line_results"][0]
        assert line_res["finding_type"] == "CONFIRMED_CALCULATION_DISCREPANCY"
        assert line_res["recalculated_amount_cents"] == 67500
        assert line_res["difference_cents"] == -27500
        assert float(line_res["quantity_used"]) == 1200.0
        assert float(line_res["exempt_quantity"]) == 200.0


def test_case_3_bravo_conflicting_amendments(clean_db):
    """Case 3: Distinguishes graduated schedule from volume schedule with 2 interpretations."""
    with TestClient(app) as client:
        res = client.post("/api/calculations/run", json={"case_id": "case-3-bravo"}, headers=REVIEWER_HEADERS)
        assert res.status_code == 201
        calc = res.json()
        assert calc["engine_status"] == "AMBIGUOUS"

        line_res = calc["line_results"][0]
        assert line_res["finding_type"] in ("AMBIGUOUS", "UNDERSPECIFIED_CONTRACT_CLAUSE")
        assert len(line_res["interpretations"]) == 2

        interps = {i["interpretation_id"]: i for i in line_res["interpretations"]}
        assert "graduated" in interps
        assert "volume" in interps
        assert interps["graduated"]["recalculated_amount_cents"] == 67500
        assert interps["volume"]["recalculated_amount_cents"] == 54000  # 1,200 * 45¢ = $540.00


def test_case_4_delta_duplicate_fee_and_credits(clean_db):
    """Case 4: FLAT fee duplicate charge and cumulative credit cap accounting."""
    with TestClient(app) as client:
        res = client.post("/api/calculations/run", json={"case_id": "case-4-delta"}, headers=REVIEWER_HEADERS)
        assert res.status_code == 201
        calc = res.json()
        assert calc["engine_status"] == "OK"
        assert calc["total_recalculated_cents"] == 12000
        assert calc["total_original_billed_cents"] == 24000
        assert calc["total_difference_cents"] == -12000  # $120.00 overcharge

        # Check credit remaining cap for the line
        cap_res = client.get(
            "/api/credits/case/case-4-delta/cap?invoice_line_id=line-c4-sub",
            headers=REVIEWER_HEADERS,
        )
        assert cap_res.status_code == 200
        cap_data = cap_res.json()
        assert cap_data["eligible_cents"] == 12000
        assert cap_data["line_adjustments_cents"] == 4000  # Only verified $40 credit reduces cap
        assert cap_data["remaining_cap_cents"] == 8000  # $80.00 remaining cap


def test_case_5_echo_included_units_and_staging(clean_db):
    """Case 5: Exempt usage removed before calculating billable overage."""
    with TestClient(app) as client:
        res = client.post("/api/calculations/run", json={"case_id": "case-5-echo"}, headers=REVIEWER_HEADERS)
        assert res.status_code == 201
        calc = res.json()
        assert calc["engine_status"] == "OK"
        # 12,500 prod - 10,000 free = 2,500 overage @ 2¢ = $50.00
        assert calc["total_recalculated_cents"] == 5000
        assert calc["total_original_billed_cents"] == 25000
        assert calc["total_difference_cents"] == -20000  # $200.00 overcharge

        line_res = calc["line_results"][0]
        assert line_res["quantity_used"] == 12500.0
        assert line_res["exempt_quantity"] == 2000.0


def test_case_6_foxtrot_percentage_discount(clean_db):
    """Case 6: Discount arithmetic, eligible vs excluded charges, and injection immunity."""
    with TestClient(app) as client:
        res = client.post("/api/calculations/run", json={"case_id": "case-6-foxtrot"}, headers=REVIEWER_HEADERS)
        assert res.status_code == 201
        calc = res.json()
        assert calc["engine_status"] == "OK"
        # Line 1: $2,000 - 15% ($300) = $1,700
        # Line 2: $300 flat (excluded from discount)
        # Total recalculated: $2,000.00; Total billed: $2,300.00 -> Diff -$300.00
        assert calc["total_recalculated_cents"] == 200000
        assert calc["total_original_billed_cents"] == 230000
        assert calc["total_difference_cents"] == -30000


def test_case_7_golf_minimum_commitment(clean_db):
    """Case 7: Minimum commitment floor raises actual metered charge, ignoring unconfirmed waiver."""
    with TestClient(app) as client:
        res = client.post("/api/calculations/run", json={"case_id": "case-7-golf"}, headers=REVIEWER_HEADERS)
        assert res.status_code == 201
        calc = res.json()
        assert calc["engine_status"] == "OK"
        # 4,200 @ 10¢ = $420.00 -> Raised to $500.00 minimum commitment floor
        # Billed: $600.00 -> Difference: -$100.00
        assert calc["total_recalculated_cents"] == 50000
        assert calc["total_original_billed_cents"] == 60000
        assert calc["total_difference_cents"] == -10000

        line_res = calc["line_results"][0]
        assert line_res["recalculated_amount_cents"] == 50000
        assert line_res["applied_minimum_commit_cents"] == 50000
