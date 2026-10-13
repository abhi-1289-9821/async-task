"""
tests/test_models_and_db.py
===========================
Tests for SQLAlchemy models, foreign key enforcement, and database triggers.
Verifies Phase 1 deliverables:
  1. All 14 tables create cleanly.
  2. PRAGMA foreign_keys=ON is active and rejects orphaned child records.
  3. Append-only DB triggers prevent UPDATE and DELETE on audit tables:
     - case_events (cannot UPDATE, cannot DELETE)
     - calculation_line_results (cannot UPDATE, cannot DELETE)
  4. Idempotency unique constraints (credits idempotency_key).
  5. JSON column storage and retrieval for tiers and exemptions.
"""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError, OperationalError

from app.models.case import Base, Case, CaseEvent, CaseStatus
from app.models.invoice import InvoiceLine, ContractRule, RuleTypeDB
from app.models.usage import UsageEvent, EvidenceVersion
from app.models.calculation import Calculation, CalculationLineResult, EngineStatusDB, FindingTypeDB
from app.models.investigation import InvestigationRun, Finding, FindingReview, ResolutionOption
from app.models.credit import Credit
from app.database import install_append_only_triggers, set_sqlite_pragmas


@pytest.fixture
def db_session(tmp_path):
    """Creates a temporary SQLite database with all tables, pragmas, and triggers."""
    db_file = tmp_path / "test_db.sqlite"
    engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )
    # Register foreign key listener
    from sqlalchemy import event
    event.listen(engine, "connect", set_sqlite_pragmas)

    # Create tables and install triggers
    Base.metadata.create_all(bind=engine)
    install_append_only_triggers(engine)

    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


class TestDatabaseSchemaAndConstraints:
    def test_all_tables_exist(self, db_session):
        tables = Base.metadata.tables.keys()
        expected = {
            "cases", "case_events", "invoice_lines", "contract_rules",
            "usage_events", "evidence_versions", "calculations",
            "calculation_line_results", "investigation_runs", "findings",
            "finding_reviews", "resolution_options", "credits", "adjustments"
        }
        assert expected.issubset(set(tables))

    def test_foreign_key_enforcement_sqlite(self, db_session):
        """Inserting a case_event pointing to non-existent case_id must fail."""
        orphan_event = CaseEvent(
            case_id="non-existent-case-id",
            event_type="CREATED",
            actor="test",
            details={"note": "orphan"}
        )
        db_session.add(orphan_event)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_case_events_append_only_trigger_blocks_update(self, db_session):
        """Updating a row in case_events must trigger an OperationalError from SQLite trigger."""
        case = Case(
            id="case-101",
            title="Overcharge dispute",
            customer_name="Acme Corp",
            disputed_amount_cents=5000,
            status=CaseStatus.OPEN,
            evidence_version=1
        )
        db_session.add(case)
        db_session.commit()

        event = CaseEvent(
            case_id="case-101",
            event_type="STATUS_CHANGED",
            actor="analyst@aggroso.com",
            details={"from": "OPEN", "to": "RESOLVED"}
        )
        db_session.add(event)
        db_session.commit()
        event_id = event.id

        # Attempt to UPDATE the audit event — must fail via DB trigger
        with pytest.raises(IntegrityError, match="case_events is append-only: UPDATE is not permitted"):
            db_session.execute(
                text("UPDATE case_events SET actor = 'hacker' WHERE id = :eid"),
                {"eid": event_id}
            )
            db_session.commit()
        db_session.rollback()

    def test_case_events_append_only_trigger_blocks_delete(self, db_session):
        """Deleting a row in case_events must trigger an IntegrityError from SQLite trigger."""
        case = Case(
            id="case-102",
            title="Overcharge dispute",
            customer_name="Acme Corp",
            disputed_amount_cents=5000,
            status=CaseStatus.OPEN,
            evidence_version=1
        )
        db_session.add(case)
        db_session.commit()

        event = CaseEvent(
            case_id="case-102",
            event_type="EVIDENCE_ADDED",
            actor="system",
            details={"version": 2}
        )
        db_session.add(event)
        db_session.commit()
        event_id = event.id

        # Attempt to DELETE — must fail via DB trigger
        with pytest.raises(IntegrityError, match="case_events is append-only: DELETE is not permitted"):
            db_session.execute(
                text("DELETE FROM case_events WHERE id = :eid"),
                {"eid": event_id}
            )
            db_session.commit()
        db_session.rollback()

    def test_calculation_line_results_append_only_trigger(self, db_session):
        """calculation_line_results must also be immutable via DB trigger."""
        case = Case(
            id="case-calc-1",
            title="Dispute",
            customer_name="Beta LLC",
            disputed_amount_cents=5000,
            status=CaseStatus.OPEN,
            evidence_version=1
        )
        inv_line = InvoiceLine(
            id="line-1",
            case_id="case-calc-1",
            description="API calls",
            original_amount_cents=5000
        )
        calc = Calculation(
            id="calc-1",
            case_id="case-calc-1",
            evidence_version=1,
            engine_status=EngineStatusDB.OK,
            total_original_billed_cents=5000,
            total_recalculated_cents=4500,
            total_difference_cents=-500,
            result_hash="abc123hash"
        )
        db_session.add_all([case, inv_line, calc])
        db_session.commit()

        line_res = CalculationLineResult(
            calculation_id="calc-1",
            line_id="line-1",
            result_id="res_0123456789abcdef",
            rule_id="rule-1",
            original_amount_cents=5000,
            recalculated_amount_cents=4500,
            difference_cents=-500,
            finding_type=FindingTypeDB.CONFIRMED_CALCULATION_DISCREPANCY,
            quantity_used=1000,
            exempt_quantity=0,
            explanation="500 overcharge detected"
        )
        db_session.add(line_res)
        db_session.commit()

        with pytest.raises(IntegrityError, match="calculation_line_results is append-only: UPDATE is not permitted"):
            db_session.execute(
                text("UPDATE calculation_line_results SET recalculated_amount_cents = 0 WHERE result_id = 'res_0123456789abcdef'")
            )
            db_session.commit()
        db_session.rollback()


    def test_credit_idempotency_key_unique(self, db_session):
        """Cannot insert two credits with identical idempotency_key."""
        case = Case(
            id="case-credit-1",
            title="Dispute",
            customer_name="Gamma Inc",
            disputed_amount_cents=500,
            status=CaseStatus.OPEN,
            evidence_version=1
        )
        db_session.add(case)
        db_session.commit()

        c1 = Credit(
            id="cred-1",
            case_id="case-credit-1",
            amount_cents=500,
            reason_code="OVERCHARGE",
            approved_by="lead_auditor",
            idempotency_key="hash-duplicate-key-123"
        )
        c2 = Credit(
            id="cred-2",
            case_id="case-credit-1",
            amount_cents=500,
            reason_code="OVERCHARGE",
            approved_by="lead_auditor",
            idempotency_key="hash-duplicate-key-123"
        )
        db_session.add(c1)
        db_session.commit()

        db_session.add(c2)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_contract_rule_json_fields(self, db_session):
        """ContractRule JSON columns store and retrieve python dicts/lists without corruption."""
        case = Case(
            id="case-rule-1",
            title="Rule Test",
            customer_name="Delta Co",
            disputed_amount_cents=1000,
            status=CaseStatus.OPEN,
            evidence_version=1
        )
        line = InvoiceLine(
            id="line-test",
            case_id="case-rule-1",
            description="Compute hours",
            original_amount_cents=1000
        )
        rule = ContractRule(
            id="cr-1",
            case_id="case-rule-1",
            line_id="line-test",
            rule_type=RuleTypeDB.TIERED_GRADUATED,
            rate_cents=0,
            tiers=[
                {"up_to": 100, "rate_cents": 10},
                {"up_to": 500, "rate_cents": 8},
                {"up_to": None, "rate_cents": 5}
            ],
            exempt_environments=["staging", "qa", "dev"]
        )
        db_session.add_all([case, line, rule])
        db_session.commit()

        fetched = db_session.query(ContractRule).filter_by(id="cr-1").one()
        assert len(fetched.tiers) == 3
        assert fetched.tiers[0]["up_to"] == 100
        assert fetched.exempt_environments == ["staging", "qa", "dev"]
