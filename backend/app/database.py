"""
database.py
===========
SQLAlchemy engine and session setup.

LOCAL (SQLite):
  - URL: sqlite:///./billing_disputes.db
  - connect_args={"check_same_thread": False} required for FastAPI's thread model
  - PRAGMA foreign_keys=ON enforced via event listener (SQLite doesn't enable it by default)
  - PRAGMA journal_mode=WAL improves concurrent read performance slightly

PRODUCTION (PostgreSQL / Neon):
  - URL from DATABASE_URL env var (postgresql+psycopg2://...)
  - Pool settings tuned for Render free tier (low connection count)

The append-only trigger on case_events is installed via DDL event after table creation.
"""

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    """Shared declarative base for all models."""
    pass


def set_sqlite_pragmas(dbapi_conn, connection_record=None):
    """
    Enable foreign key enforcement and WAL mode for every new SQLite connection.
    SQLite disables FK checks by default; without this, ForeignKey constraints
    are silently ignored.
    """
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def _make_engine():
    if settings.database_url.startswith("sqlite"):
        engine = create_engine(
            settings.database_url,
            connect_args={"check_same_thread": False},
            echo=settings.debug,
        )
        event.listen(engine, "connect", set_sqlite_pragmas)
        return engine
    else:
        # PostgreSQL — used on Render / Neon
        engine = create_engine(
            settings.database_url,
            pool_size=3,        # Neon free tier has low connection limits
            max_overflow=2,
            pool_pre_ping=True, # detect stale connections after cold start
            echo=settings.debug,
        )
        return engine


engine = _make_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """
    FastAPI dependency: yields a database session, closes it when the request ends.
    Usage: db: Session = Depends(get_db)
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_all_tables():
    """
    Create all tables from models. Used for local dev and tests.
    """
    # Import all models so SQLAlchemy sees them before create_all()
    import app.models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    run_auto_migrations(engine)
    install_append_only_triggers(engine)


def run_auto_migrations(target_engine=None):
    """Adds missing columns to existing tables for SQLite and PostgreSQL gracefully."""
    target = target_engine or engine
    dialect = target.dialect.name
    with target.connect() as conn:
        if dialect == "sqlite":
            try:
                cols = [row[1] for row in conn.execute(text("PRAGMA table_info(cases)")).fetchall()]
                if cols:
                    if "invoice_id" not in cols:
                        conn.execute(text("ALTER TABLE cases ADD COLUMN invoice_id VARCHAR(64)"))
                    if "currency" not in cols:
                        conn.execute(text("ALTER TABLE cases ADD COLUMN currency VARCHAR(10) DEFAULT 'USD' NOT NULL"))
                    if "claimed_usage_quantity" not in cols:
                        conn.execute(text("ALTER TABLE cases ADD COLUMN claimed_usage_quantity NUMERIC(20, 6)"))
                    if "claimed_usage_uom" not in cols:
                        conn.execute(text("ALTER TABLE cases ADD COLUMN claimed_usage_uom VARCHAR(50)"))
            except Exception:
                pass

            try:
                adj_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(adjustments)")).fetchall()]
                if adj_cols:
                    if "is_verified" not in adj_cols:
                        conn.execute(text("ALTER TABLE adjustments ADD COLUMN is_verified BOOLEAN DEFAULT 1 NOT NULL"))
                    if "evidence_source" not in adj_cols:
                        conn.execute(text("ALTER TABLE adjustments ADD COLUMN evidence_source VARCHAR(255)"))
            except Exception:
                pass
            conn.commit()
        elif dialect == "postgresql":
            try:
                conn.execute(text("ALTER TABLE cases ADD COLUMN IF NOT EXISTS invoice_id VARCHAR(64)"))
                conn.execute(text("ALTER TABLE cases ADD COLUMN IF NOT EXISTS currency VARCHAR(10) DEFAULT 'USD' NOT NULL"))
                conn.execute(text("ALTER TABLE cases ADD COLUMN IF NOT EXISTS claimed_usage_quantity NUMERIC(20, 6)"))
                conn.execute(text("ALTER TABLE cases ADD COLUMN IF NOT EXISTS claimed_usage_uom VARCHAR(50)"))
                conn.execute(text("ALTER TABLE adjustments ADD COLUMN IF NOT EXISTS is_verified BOOLEAN DEFAULT TRUE NOT NULL"))
                conn.execute(text("ALTER TABLE adjustments ADD COLUMN IF NOT EXISTS evidence_source VARCHAR(255)"))
                conn.commit()
            except Exception:
                pass


def install_append_only_triggers(target_engine=None):
    """
    Install DB-level triggers that block UPDATE and DELETE on audit and immutable tables:
      - case_events (audit trail)
      - calculation_line_results (immutable billing calculation output)
      - credits (approved credits)
      - finding_reviews (human reviewer decisions)
      - evidence_versions (evidence snapshots)
      - findings (original AI text is immutable; DELETE blocked)
    Enforces the append-only / immutable invariant at the database layer.
    """
    target = target_engine or engine
    dialect = target.dialect.name

    if dialect == "sqlite":
        with target.connect() as conn:
            # case_events
            conn.execute(text("""
                CREATE TRIGGER IF NOT EXISTS trg_case_events_no_update
                BEFORE UPDATE ON case_events
                BEGIN
                    SELECT RAISE(ABORT, 'case_events is append-only: UPDATE is not permitted');
                END;
            """))
            conn.execute(text("""
                CREATE TRIGGER IF NOT EXISTS trg_case_events_no_delete
                BEFORE DELETE ON case_events
                BEGIN
                    SELECT RAISE(ABORT, 'case_events is append-only: DELETE is not permitted');
                END;
            """))
            # calculation_line_results
            conn.execute(text("""
                CREATE TRIGGER IF NOT EXISTS trg_calc_results_no_update
                BEFORE UPDATE ON calculation_line_results
                BEGIN
                    SELECT RAISE(ABORT, 'calculation_line_results is append-only: UPDATE is not permitted');
                END;
            """))
            conn.execute(text("""
                CREATE TRIGGER IF NOT EXISTS trg_calc_results_no_delete
                BEFORE DELETE ON calculation_line_results
                BEGIN
                    SELECT RAISE(ABORT, 'calculation_line_results is append-only: DELETE is not permitted');
                END;
            """))
            # credits
            conn.execute(text("""
                CREATE TRIGGER IF NOT EXISTS trg_credits_no_update
                BEFORE UPDATE ON credits
                BEGIN
                    SELECT RAISE(ABORT, 'credits is append-only: UPDATE is not permitted');
                END;
            """))
            conn.execute(text("""
                CREATE TRIGGER IF NOT EXISTS trg_credits_no_delete
                BEFORE DELETE ON credits
                BEGIN
                    SELECT RAISE(ABORT, 'credits is append-only: DELETE is not permitted');
                END;
            """))
            # finding_reviews
            conn.execute(text("""
                CREATE TRIGGER IF NOT EXISTS trg_finding_reviews_no_update
                BEFORE UPDATE ON finding_reviews
                BEGIN
                    SELECT RAISE(ABORT, 'finding_reviews is append-only: UPDATE is not permitted');
                END;
            """))
            conn.execute(text("""
                CREATE TRIGGER IF NOT EXISTS trg_finding_reviews_no_delete
                BEFORE DELETE ON finding_reviews
                BEGIN
                    SELECT RAISE(ABORT, 'finding_reviews is append-only: DELETE is not permitted');
                END;
            """))
            # findings (block DELETE; block raw_ai_text UPDATE)
            conn.execute(text("""
                CREATE TRIGGER IF NOT EXISTS trg_findings_no_delete
                BEFORE DELETE ON findings
                BEGIN
                    SELECT RAISE(ABORT, 'findings is append-only: DELETE is not permitted');
                END;
            """))
            conn.execute(text("""
                CREATE TRIGGER IF NOT EXISTS trg_findings_raw_text_no_update
                BEFORE UPDATE OF raw_ai_text ON findings
                BEGIN
                    SELECT RAISE(ABORT, 'findings raw_ai_text is immutable: UPDATE is not permitted');
                END;
            """))
            # evidence_versions
            conn.execute(text("""
                CREATE TRIGGER IF NOT EXISTS trg_evidence_versions_no_update
                BEFORE UPDATE ON evidence_versions
                BEGIN
                    SELECT RAISE(ABORT, 'evidence_versions is append-only: UPDATE is not permitted');
                END;
            """))
            conn.execute(text("""
                CREATE TRIGGER IF NOT EXISTS trg_evidence_versions_no_delete
                BEFORE DELETE ON evidence_versions
                BEGIN
                    SELECT RAISE(ABORT, 'evidence_versions is append-only: DELETE is not permitted');
                END;
            """))
            conn.commit()

    elif dialect == "postgresql":
        with target.connect() as conn:
            conn.execute(text("""
                CREATE OR REPLACE FUNCTION block_append_only_modification()
                RETURNS trigger AS $$
                BEGIN
                    RAISE EXCEPTION '% is immutable / append-only: modification is not permitted', TG_TABLE_NAME;
                END;
                $$ LANGUAGE plpgsql;
            """))
            for tbl in ["case_events", "calculation_line_results", "credits", "finding_reviews", "evidence_versions"]:
                conn.execute(text(f"""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_{tbl}_append_only') THEN
                            CREATE TRIGGER trg_{tbl}_append_only
                            BEFORE UPDATE OR DELETE ON {tbl}
                            FOR EACH ROW EXECUTE FUNCTION block_append_only_modification();
                        END IF;
                    END $$;
                """))
            # findings: block delete
            conn.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_findings_no_delete') THEN
                        CREATE TRIGGER trg_findings_no_delete
                        BEFORE DELETE ON findings
                        FOR EACH ROW EXECUTE FUNCTION block_append_only_modification();
                    END IF;
                END $$;
            """))
            # findings: block update of raw_ai_text (while allowing is_stale updates)
            conn.execute(text("""
                CREATE OR REPLACE FUNCTION block_findings_raw_ai_text_update()
                RETURNS trigger AS $$
                BEGIN
                    IF OLD.raw_ai_text IS DISTINCT FROM NEW.raw_ai_text THEN
                        RAISE EXCEPTION 'findings raw_ai_text is immutable: UPDATE is not permitted';
                    END IF;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
            """))
            conn.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_findings_raw_text_no_update') THEN
                        CREATE TRIGGER trg_findings_raw_text_no_update
                        BEFORE UPDATE ON findings
                        FOR EACH ROW EXECUTE FUNCTION block_findings_raw_ai_text_update();
                    END IF;
                END $$;
            """))
            conn.commit()
    else:
        # Unsupported dialect or in-memory mock: skip gracefully
        pass

