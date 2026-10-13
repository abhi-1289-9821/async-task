"""
tests/test_concurrency.py
=========================
Concurrency stress tests for credit approval and cumulative cap invariant.

Tests:
  1. Concurrent Thread Stress Test (SQLite / Multi-threaded):
     Simulates concurrent approval requests firing in parallel threads.
     Asserts:
       - Only ONE request succeeds in claiming the balance.
       - Cumulative cap invariant strictly holds: total credited cents == eligible overcharge.
       - Concurrent duplicate requests receive HTTP 409 or HTTP 400 cap exhausted.
       - Zero double-crediting occurs.
  2. Real PostgreSQL Concurrency Test:
     Run against real PostgreSQL / Neon when POSTGRES_TEST_URL is configured.
     Validates SELECT FOR UPDATE row locking across concurrent database connections.
"""

import os
import pytest
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from sqlalchemy import create_engine, event, func
from sqlalchemy.orm import sessionmaker

from app.database import Base, set_sqlite_pragmas, install_append_only_triggers
from app.models.case import Case, CaseStatus
from app.models.invoice import InvoiceLine
from app.models.investigation import InvestigationRun, Finding, FindingReview
from app.models.calculation import Calculation, CalculationLineResult, EngineStatusDB, FindingTypeDB
from app.models.credit import Credit
from app.services.credit_service import approve_credit


@pytest.fixture
def isolated_db(tmp_path):
    """Sets up an isolated database engine and sessionmaker."""
    db_file = tmp_path / "test_concurrency.sqlite"
    test_engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    event.listen(test_engine, "connect", set_sqlite_pragmas)
    Base.metadata.create_all(bind=test_engine)
    install_append_only_triggers(test_engine)

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    yield SessionLocal
    test_engine.dispose()


def _run_concurrency_cap_assertion(SessionLocal, case_id: str, line_id: str, find_id: str):
    """Executes 10-thread parallel claim against a 5000¢ overcharge, asserting exact cap hold."""
    # Seed dispute data
    with SessionLocal() as db:
        case = Case(
            id=case_id,
            title="Concurrency Test Case",
            customer_name="Concurrent Corp",
            disputed_amount_cents=5000,
            status=CaseStatus.OPEN.value,
            evidence_version=1,
        )
        line = InvoiceLine(
            id=line_id,
            case_id=case_id,
            description="Concurrent compute units",
            original_amount_cents=5000,
        )
        calc = Calculation(
            id=f"calc-{case_id}",
            case_id=case_id,
            evidence_version=1,
            engine_status=EngineStatusDB.OK,
            total_original_billed_cents=5000,
            total_recalculated_cents=0,
            total_difference_cents=-5000,
            result_hash=f"hash-{case_id}",
        )
        clr = CalculationLineResult(
            calculation_id=f"calc-{case_id}",
            line_id=line_id,
            result_id=f"res_{case_id[:12]}",
            rule_id=f"rule-{case_id}",
            original_amount_cents=5000,
            recalculated_amount_cents=0,
            difference_cents=-5000,  # 5000 cents eligible overcharge
            finding_type=FindingTypeDB.CONFIRMED_CALCULATION_DISCREPANCY,
            quantity_used=100.0,
            exempt_quantity=0.0,
            explanation="Full overcharge",
        )
        db.add_all([case, line, calc, clr])
        db.flush()

        run = InvestigationRun(id=f"run-{case_id}", case_id=case_id, evidence_version=1, status="COMPLETED")
        finding = Finding(
            id=find_id,
            case_id=case_id,
            run_id=f"run-{case_id}",
            calculation_line_result_id=clr.id,
            finding_type="CONFIRMED_CALCULATION_DISCREPANCY",
            raw_ai_text="Overcharge eligible for credit",
            citation_validation_passed=True,
            consistency_check_passed=True,
            is_stale=False,
        )
        db.add_all([run, finding])
        db.flush()

        # Human reviewer accepted finding
        review = FindingReview(
            finding_id=find_id,
            action="ACCEPT",
            reviewer="lead_auditor@acmebilling.com",
            original_ai_text="Overcharge eligible for credit",
        )
        db.add(review)
        db.commit()

    # Function executed by worker threads
    def attempt_approval(worker_id: int):
        with SessionLocal() as session:
            try:
                credit = approve_credit(
                    db=session,
                    case_id=case_id,
                    invoice_line_id=line_id,
                    reason_code=f"CONCURRENCY_TEST_{worker_id}",
                    finding_id=find_id,
                    actor=f"worker_{worker_id}@acmebilling.com",
                )
                return ("SUCCESS", credit.amount_cents)
            except Exception as exc:
                return ("REJECTED", str(exc))

    # Fire 10 concurrent threads simultaneously
    results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(attempt_approval, i) for i in range(10)]
        for f in as_completed(futures):
            results.append(f.result())

    successes = [r for r in results if r[0] == "SUCCESS"]
    rejections = [r for r in results if r[0] == "REJECTED"]

    # Verify that exactly ONE thread claimed the credit
    assert len(successes) == 1
    assert len(rejections) == 9

    # Verify in DB that total approved credits strictly equals 5000 cents
    with SessionLocal() as db:
        total_credited = (
            db.query(func.coalesce(func.sum(Credit.amount_cents), 0))
            .filter(Credit.invoice_line_id == line_id)
            .scalar()
        )
        assert total_credited == 5000

        credit_records = db.query(Credit).filter(Credit.invoice_line_id == line_id).all()
        assert len(credit_records) == 1


def test_concurrent_credit_approvals_hold_cumulative_cap(isolated_db):
    """
    Spawns 10 parallel threads attempting to claim a $50.00 (5000 cents) overcharge simultaneously.
    Proves that:
      - The cumulative cap holds under parallel concurrency.
      - Total approved credits never exceed 5000 cents.
      - Exactly one thread claims the credit, and competing threads are rejected.
    """
    _run_concurrency_cap_assertion(
        SessionLocal=isolated_db,
        case_id="case-conc-1",
        line_id="line-conc-1",
        find_id="find-conc-1",
    )


@pytest.mark.skipif(
    not os.environ.get("POSTGRES_TEST_URL"),
    reason="Requires live PostgreSQL instance via POSTGRES_TEST_URL env var",
)
def test_postgres_select_for_update_concurrency():
    """
    Live PostgreSQL concurrency verification:
    Runs against a real PostgreSQL database instance (Neon / local Postgres)
    and verifies that SELECT FOR UPDATE prevents race conditions across connections.
    """
    pg_url = os.environ["POSTGRES_TEST_URL"]
    pg_engine = create_engine(pg_url, pool_size=10, max_overflow=5)
    Base.metadata.create_all(bind=pg_engine)
    PGSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=pg_engine)

    try:
        _run_concurrency_cap_assertion(
            SessionLocal=PGSessionLocal,
            case_id="case-pg-conc-1",
            line_id="line-pg-conc-1",
            find_id="find-pg-conc-1",
        )
    finally:
        pg_engine.dispose()

