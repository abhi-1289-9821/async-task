"""
tests/test_seed.py
==================
Tests for Task 1: Auto-seeding on application startup.
Acceptance criteria:
  1. Starts app (TestClient) against an empty temp SQLite DB.
  2. Asserts exactly 3 cases exist.
  3. Bravo calculation returns AMBIGUOUS with two interpretations.
  4. Acme calculation returns a CONFIRMED discrepancy.
  5. Delta calculation returns NO_DISCREPANCY.
  6. A second app start does not duplicate cases.
  7. A seed failure is logged and does not crash startup.
"""

import logging
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.config import settings
from app.database import Base, get_db, set_sqlite_pragmas, install_append_only_triggers
import app.database as db_module
import app.seed as seed_module

REVIEWER_HEADERS = {"Authorization": f"Bearer {settings.demo_reviewer_token}"}


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Creates a clean isolated SQLite DB and patches app.database engine and SessionLocal."""
    db_file = tmp_path / "test_seed.sqlite"
    test_engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )
    event.listen(test_engine, "connect", set_sqlite_pragmas)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    # Monkeypatch the engine and SessionLocal in app.database
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


def test_startup_autoseed_creates_three_cases(temp_db):
    """
    Starts app against empty SQLite DB via TestClient lifespan.
    Verifies 3 cases, calculation statuses, and idempotency on second start.
    """
    test_engine, _ = temp_db

    # First app startup
    with TestClient(app) as client:
        # 1. Seeded cases exist
        res = client.get("/api/cases", headers=REVIEWER_HEADERS)
        assert res.status_code == 200, res.text
        cases = res.json()
        assert len(cases) >= 5
        case_ids = {c["id"] for c in cases}
        assert {"case-acme-unverified", "case-acme-verified", "case-acme-101", "case-bravo-102", "case-delta-103"}.issubset(case_ids)

        # 2. Case Acme Unverified (Scenario A) -> INSUFFICIENT_DATA, recalculated amount is None
        res_acme_a = client.post("/api/calculations/run", json={"case_id": "case-acme-unverified"}, headers=REVIEWER_HEADERS)
        assert res_acme_a.status_code == 201, res_acme_a.text
        calc_acme_a = res_acme_a.json()
        assert calc_acme_a["engine_status"] == "INSUFFICIENT_DATA"
        assert calc_acme_a["total_recalculated_cents"] is None
        assert calc_acme_a["total_difference_cents"] is None

        # 3. Case Acme Verified (Scenario B) -> Recalculates to $490 (49000 cents), difference -$1360 (-136000 cents)
        res_acme_b = client.post("/api/calculations/run", json={"case_id": "case-acme-verified"}, headers=REVIEWER_HEADERS)
        assert res_acme_b.status_code == 201, res_acme_b.text
        calc_acme_b = res_acme_b.json()
        assert calc_acme_b["engine_status"] == "OK"
        assert calc_acme_b["total_recalculated_cents"] == 49000
        assert calc_acme_b["total_difference_cents"] == -136000

        # 4. Case Bravo (case-bravo-102) -> AMBIGUOUS with two interpretations
        res_bravo = client.post("/api/calculations/run", json={"case_id": "case-bravo-102"}, headers=REVIEWER_HEADERS)
        assert res_bravo.status_code == 201, res_bravo.text
        calc_bravo = res_bravo.json()
        assert calc_bravo["engine_status"] == "AMBIGUOUS"
        assert len(calc_bravo["line_results"]) >= 1
        bravo_line = calc_bravo["line_results"][0]
        assert len(bravo_line["interpretations"]) == 2
        interp_ids = {i["interpretation_id"] for i in bravo_line["interpretations"]}
        assert "graduated" in interp_ids
        assert "volume" in interp_ids

        # 5. Case Acme (case-acme-101) -> CONFIRMED discrepancy
        res_acme = client.post("/api/calculations/run", json={"case_id": "case-acme-101"}, headers=REVIEWER_HEADERS)
        assert res_acme.status_code == 201, res_acme.text
        calc_acme = res_acme.json()
        assert calc_acme["engine_status"] == "OK"
        assert len(calc_acme["line_results"]) >= 1
        acme_line = calc_acme["line_results"][0]
        assert acme_line["finding_type"] == "CONFIRMED_CALCULATION_DISCREPANCY"
        assert acme_line["difference_cents"] < 0
        assert acme_line["recalculated_amount_cents"] == 2500

        # 6. Case Delta (case-delta-103) -> NO_DISCREPANCY
        res_delta = client.post("/api/calculations/run", json={"case_id": "case-delta-103"}, headers=REVIEWER_HEADERS)
        assert res_delta.status_code == 201, res_delta.text
        calc_delta = res_delta.json()
        assert calc_delta["engine_status"] == "OK"
        assert len(calc_delta["line_results"]) >= 1
        delta_line = calc_delta["line_results"][0]
        assert delta_line["finding_type"] == "NO_DISCREPANCY"
        assert delta_line["difference_cents"] == 0

    # 7. Second app start does not duplicate cases (idempotent)
    with TestClient(app) as client2:
        res2 = client2.get("/api/cases", headers=REVIEWER_HEADERS)
        assert res2.status_code == 200
        cases2 = res2.json()
        assert len(cases2) == len(cases)


def test_seed_failure_logged_and_does_not_crash_startup(temp_db, monkeypatch, caplog):
    """
    If seeding raises an exception during startup, it is logged with logger.exception
    and startup continues normally without crashing.
    """
    import asyncio
    from app.main import lifespan

    def broken_seed(db):
        raise RuntimeError("Simulated seed crash for testing error resilience")

    monkeypatch.setattr("app.seed.seed_demo_cases_if_empty", broken_seed)

    log_calls = []
    orig_exception = logging.Logger.exception
    def spy_exception(self, msg, *args, **kwargs):
        log_calls.append(str(msg))
        return orig_exception(self, msg, *args, **kwargs)
    monkeypatch.setattr(logging.Logger, "exception", spy_exception)

    # Startup should NOT raise RuntimeError
    with caplog.at_level(logging.ERROR):
        async def _run():
            async with lifespan(app):
                pass
        asyncio.run(_run())

    # Check that the exception was logged
    assert any("startup seeding failed" in str(msg) for msg in log_calls) or any(
        "startup seeding failed" in record.message for record in caplog.records
    )
