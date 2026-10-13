"""
models/usage.py
================
UsageEvent and EvidenceVersion tables.

UsageEvent: a single usage measurement record for a case.
EvidenceVersion: a snapshot of all inputs for a case at a point in time.
  - SHA-256 hash of (invoice_lines JSON + contract_rules JSON + usage_events JSON)
  - Bumped every time evidence changes (any case status)
  - Prior findings and investigation runs reference the version number they used
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class UsageEvent(Base):
    """
    One usage measurement for a case.

    quantity: stored as Numeric(20,6) to preserve Decimal precision.
    environment: "production", "staging", etc. — compared against rule's exempt_environments.
    is_quarantined: True if the billing engine rejected this event.
    quarantine_reason: why it was rejected.
    """
    __tablename__ = "usage_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    line_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("invoice_lines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    quantity: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    environment: Mapped[str] = mapped_column(String(50), nullable=False)
    event_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    is_quarantined: Mapped[bool] = mapped_column(Integer, nullable=False, default=0)
    quarantine_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    case: Mapped["Case"] = relationship(back_populates="usage_events")  # noqa: F821


class EvidenceVersion(Base):
    """
    Immutable snapshot of what evidence existed for a case at a given version.

    version_number: 1, 2, 3, ... incremented on each upload.
    content_hash: SHA-256 of the serialised inputs (lines + rules + events).
      Used to detect whether inputs actually changed, and to bind investigation
      runs and calculations to a specific evidence state.
    created_by: actor who triggered this version bump.
    """
    __tablename__ = "evidence_versions"
    __table_args__ = (
        UniqueConstraint("case_id", "version_number", name="uq_evidence_versions_case_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # SHA-256 hex
    created_by: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    case: Mapped["Case"] = relationship(back_populates="evidence_versions")  # noqa: F821
