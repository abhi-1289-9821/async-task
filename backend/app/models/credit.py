"""
models/credit.py
================
Credit and Adjustment tables.

Credit: one approved mock credit. Idempotent: UNIQUE on idempotency_key.
  - idempotency_key: SHA-256 of (case_id + invoice_line_id + reason_code)
  - amount_cents: fetched from calculation_line_result at approval time; NEVER from LLM output
  - requires_accepted_finding: credit approval checks that a non-stale ACCEPTED finding exists
  - Approved by a REVIEWER (demo role); AI recommendations are not approvals

Adjustment: credits/discounts applied by the account team BEFORE this dispute.
  - Used to calculate the cumulative credit cap (cannot exceed eligible overcharge)
  - Cannot be created via the billing agent — must be seeded or uploaded as evidence
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Credit(Base):
    """
    One approved mock credit for a billing dispute.

    IDEMPOTENCY:
      - idempotency_key = SHA-256(case_id + invoice_line_id + reason_code)
      - UNIQUE constraint at DB level
      - Duplicate requests: HTTP 409

    AMOUNT SAFETY:
      - amount_cents comes from calculation_line_result_id lookup; never from LLM
      - The credit_service checks: amount <= (overcharge - prior_credits - adjustments)

    CONCURRENCY:
      - credit_service uses SELECT FOR UPDATE (Postgres) / BEGIN IMMEDIATE (SQLite)
        so the cumulative cap check + insert is atomic
    """
    __tablename__ = "credits"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_credits_idempotency_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resolution_option_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("resolution_options.id", ondelete="SET NULL"), nullable=True
    )
    calculation_line_result_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("calculation_line_results.id", ondelete="SET NULL"), nullable=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    reason_code: Mapped[str] = mapped_column(String(50), nullable=False)
    reason_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    approved_by: Mapped[str] = mapped_column(String(50), nullable=False)   # reviewer identity
    approved_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    case: Mapped["Case"] = relationship(back_populates="credits")  # noqa: F821
    resolution_option: Mapped[Optional["ResolutionOption"]] = relationship(back_populates="credits")  # noqa: F821


class Adjustment(Base):
    """
    A prior credit/discount applied by the account team before this dispute.
    Used to compute the cumulative credit cap.
    Cannot be created by the billing agent.
    """
    __tablename__ = "adjustments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    case: Mapped["Case"] = relationship(back_populates="adjustments")  # noqa: F821
