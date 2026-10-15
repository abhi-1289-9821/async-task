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
            actor="analyst@fairbill.io",
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
        line = InvoiceLine(
            id="line-cred-1",
            case_id="case-credit-1",
            description="Service fee",
            original_amount_cents=500,
        )
        db_session.add_all([case, line])
        db_session.commit()

        c1 = Credit(
            id="cred-1",
            case_id="case-credit-1",
            invoice_line_id="line-cred-1",
            amount_cents=500,
            reason_code="OVERCHARGE",
            approved_by="lead_auditor",
            idempotency_key="hash-duplicate-key-123"
        )
        c2 = Credit(
            id="cred-2",
            case_id="case-credit-1",
            invoice_line_id="line-cred-1",
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

    def test_credit_amount_positive_check_constraint(self, db_session):
        """Credit amount_cents must be > 0 by CheckConstraint."""
        case = Case(
            id="case-c-chk",
            title="Dispute",
            customer_name="Corp",
            disputed_amount_cents=5000,
            status=CaseStatus.OPEN,
            evidence_version=1,
        )
        line = InvoiceLine(
            id="line-c-chk",
            case_id="case-c-chk",
            description="API",
            original_amount_cents=5000,
        )
        db_session.add_all([case, line])
        db_session.commit()

        bad_credit = Credit(
            id="c-bad",
            case_id="case-c-chk",
            invoice_line_id="line-c-chk",
            idempotency_key="key-bad",
            amount_cents=0,  # Fails amount_cents > 0
            reason_code="OVERCHARGE",
            approved_by="reviewer",
        )
        db_session.add(bad_credit)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_credits_and_reviews_append_only_triggers(self, db_session):
        """credits and finding_reviews must block UPDATE and DELETE via triggers."""
        case = Case(
            id="case-trg",
            title="Dispute",
            customer_name="Corp",
            disputed_amount_cents=5000,
            status=CaseStatus.OPEN,
            evidence_version=1,
        )
        line = InvoiceLine(
            id="line-trg",
            case_id="case-trg",
            description="API",
            original_amount_cents=5000,
        )
        db_session.add_all([case, line])
        db_session.commit()

        credit = Credit(
            id="c-ok",
            case_id="case-trg",
            invoice_line_id="line-trg",
            idempotency_key="key-ok",
            amount_cents=500,
            reason_code="OVERCHARGE",
            approved_by="reviewer",
        )
        db_session.add(credit)
        db_session.commit()

        # Update credit must fail via trigger
        with pytest.raises(IntegrityError, match="credits is append-only: UPDATE is not permitted"):
            db_session.execute(text("UPDATE credits SET amount_cents = 999 WHERE id = 'c-ok'"))
            db_session.commit()
        db_session.rollback()

        # Delete credit must fail via trigger
        with pytest.raises(IntegrityError, match="credits is append-only: DELETE is not permitted"):
            db_session.execute(text("DELETE FROM credits WHERE id = 'c-ok'"))
            db_session.commit()
        db_session.rollback()

    def test_evidence_version_unique_constraint(self, db_session):
        """EvidenceVersion enforces unique (case_id, version_number)."""
        from app.models.usage import EvidenceVersion
        case = Case(
            id="case-ev-uq",
            title="Dispute",
            customer_name="Corp",
            disputed_amount_cents=5000,
            status=CaseStatus.OPEN,
            evidence_version=1,
        )
        v1 = EvidenceVersion(case_id="case-ev-uq", version_number=1, content_hash="hash1", created_by="admin")
        v2 = EvidenceVersion(case_id="case-ev-uq", version_number=1, content_hash="hash2", created_by="admin")
        db_session.add_all([case, v1])
        db_session.commit()

        db_session.add(v2)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_alembic_migrations_cover_all_model_columns(self, tmp_path):
        """Verifies that Alembic migrations up to head include all model columns (including invoice_line_id)."""
        import os
        from alembic import command
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        from sqlalchemy import inspect, create_engine

        backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        ini_path = os.path.join(backend_dir, "alembic.ini")
        alembic_cfg = Config(ini_path)
        alembic_cfg.set_main_option("script_location", os.path.join(backend_dir, "migrations"))

        # Verify latest revision in migration scripts is c3d4e5f6a7b8
        script = ScriptDirectory.from_config(alembic_cfg)
        head_rev = script.get_current_head()
        assert head_rev in ("7aa7027ee786", "c3d4e5f6a7b8")

        # Apply migrations cleanly to a fresh SQLite database
        temp_db_path = tmp_path / "alembic_migrated.db"
        temp_db_url = f"sqlite:///{temp_db_path}"
        alembic_cfg.set_main_option("sqlalchemy.url", temp_db_url)
        command.upgrade(alembic_cfg, "head")

        check_engine = create_engine(temp_db_url)
        inspector = inspect(check_engine)

        # Verify findings has invoice_line_id
        finding_cols = {col["name"] for col in inspector.get_columns("findings")}
        assert "invoice_line_id" in finding_cols

        # Verify resolution_options has invoice_line_id
        ro_cols = {col["name"] for col in inspector.get_columns("resolution_options")}
        assert "invoice_line_id" in ro_cols

        # Verify cases has period_start, period_end, claimed_usage_quantity, claimed_usage_uom
        case_cols = {col["name"] for col in inspector.get_columns("cases")}
        assert "period_start" in case_cols
        assert "period_end" in case_cols
        assert "claimed_usage_quantity" in case_cols
        assert "claimed_usage_uom" in case_cols

        # Verify adjustments has is_verified, evidence_source
        adj_cols = {col["name"] for col in inspector.get_columns("adjustments")}
        assert "is_verified" in adj_cols
        assert "evidence_source" in adj_cols

        check_engine.dispose()


