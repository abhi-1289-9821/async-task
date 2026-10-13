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
    LIMITATION: This is NOT a migration system. If you add a column to an
    existing table, drop and recreate the DB or write an Alembic migration.
    Alembic migrations are used for production (Phase 2+).
    """
    # Import all models so SQLAlchemy sees them before create_all()
    import app.models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    install_append_only_triggers(engine)


def install_append_only_triggers(target_engine=None):
    """
    Install DB-level triggers that block UPDATE and DELETE on audit tables:
      - case_events (audit trail)
      - calculation_line_results (immutable billing calculation output)
    This enforces the append-only invariant at the database layer, not just at the ORM layer.

    SQLite: uses BEFORE UPDATE / BEFORE DELETE triggers with RAISE(ABORT, ...).
    PostgreSQL: triggers are added in Alembic migrations.
    """
    target = target_engine or engine
    # In SQLite, install the triggers
    with target.connect() as conn:
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
        conn.commit()

