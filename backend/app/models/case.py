"""
models/case.py
==============
Case table and case_events append-only audit table.

Case state machine (valid transitions enforced in transition_service.py):
  OPEN → AWAITING_INFO   (operator requests more info)
  OPEN → RESOLVED        (reviewer approves resolution)
  AWAITING_INFO → OPEN   (evidence uploaded)
  AWAITING_INFO → RESOLVED
  RESOLVED → REOPENED    (new evidence uploaded — only RESOLVED can reopen)
  REOPENED → OPEN        (re-investigation triggered)
  REOPENED → AWAITING_INFO
  REOPENED → RESOLVED

Invalid transitions return HTTP 409.

New evidence in ANY status bumps the evidence version and marks findings stale.
Status becomes REOPENED only when arriving from RESOLVED.
"""

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class CaseStatus(str, enum.Enum):
    OPEN = "OPEN"
    AWAITING_INFO = "AWAITING_INFO"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"


# Valid transitions: (from_status, to_status)
VALID_TRANSITIONS: set[tuple[str, str]] = {
    ("OPEN",          "AWAITING_INFO"),
    ("OPEN",          "RESOLVED"),
    ("AWAITING_INFO", "OPEN"),
    ("AWAITING_INFO", "RESOLVED"),
    ("RESOLVED",      "REOPENED"),
    ("REOPENED",      "OPEN"),
    ("REOPENED",      "AWAITING_INFO"),
    ("REOPENED",      "RESOLVED"),
}


class Case(Base):
    """
    One billing dispute case.

    evidence_version: incremented each time new evidence is added (any status).
    customer_name is fictional demo data only — never real PII.
    """
    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_name: Mapped[str] = mapped_column(String(100), nullable=False)
    invoice_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="USD")
    claimed_usage_quantity: Mapped[Optional[float]] = mapped_column(Numeric(20, 6), nullable=True)
    claimed_usage_uom: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    disputed_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    dispute_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(CaseStatus, name="case_status_enum", create_constraint=True),
        nullable=False,
        default=CaseStatus.OPEN.value,
    )
    evidence_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    period_start: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    period_end: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships (back-populated by child models)
    invoice_lines:      Mapped[list["InvoiceLine"]]    = relationship(back_populates="case", cascade="all, delete-orphan")  # noqa: F821
    contract_rules:     Mapped[list["ContractRule"]]   = relationship(back_populates="case", cascade="all, delete-orphan")  # noqa: F821
    usage_events:       Mapped[list["UsageEvent"]]     = relationship(back_populates="case", cascade="all, delete-orphan")  # noqa: F821
    adjustments:        Mapped[list["Adjustment"]]     = relationship(back_populates="case", cascade="all, delete-orphan")  # noqa: F821
    evidence_versions:  Mapped[list["EvidenceVersion"]] = relationship(back_populates="case", cascade="all, delete-orphan")  # noqa: F821
    calculations:       Mapped[list["Calculation"]]    = relationship(back_populates="case", cascade="all, delete-orphan")  # noqa: F821
    investigation_runs: Mapped[list["InvestigationRun"]] = relationship(back_populates="case", cascade="all, delete-orphan")  # noqa: F821
    credits:            Mapped[list["Credit"]]         = relationship(back_populates="case", cascade="all, delete-orphan")  # noqa: F821
    events:             Mapped[list["CaseEvent"]]      = relationship(back_populates="case", cascade="all, delete-orphan")  # noqa: F821


class CaseEvent(Base):
    """
    Append-only audit log for everything that happens to a case.

    ENFORCEMENT STRATEGY:
    - At the ORM layer: no update/delete methods are ever called on this table.
    - At the DB layer: a trigger (DDL event) blocks UPDATE and DELETE in SQLite.
      For PostgreSQL, the trigger is added in the Alembic migration.
    - This is tested in test_audit.py (Phase 2).

    actor: "REVIEWER", "VIEWER", or "SYSTEM"
    event_type: e.g. "STATUS_CHANGE", "EVIDENCE_UPLOAD", "CALCULATION_RUN", etc.
    details: arbitrary JSON for structured payload (amounts, versions, etc.)
    correlation_id: links events across a single HTTP request
    """
    __tablename__ = "case_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String(50), nullable=False)
    details: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    correlation_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    case: Mapped["Case"] = relationship(back_populates="events")
