"""
models/invoice.py
=================
InvoiceLine and ContractRule tables.

InvoiceLine: one line on the original disputed invoice.
ContractRule: one pricing rule for one invoice line.

ContractRule stores tiers as JSON (list of {"up_to": int|null, "price_per_unit_cents": int}).
exempt_environments stored as JSON list.

Design note: rules are NOT shared across cases — each case gets its own rule rows.
This avoids version conflicts if a contract changes between cases.
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
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class RuleTypeDB(str, enum.Enum):
    FLAT = "FLAT"
    PER_UNIT = "PER_UNIT"
    TIERED_GRADUATED = "TIERED_GRADUATED"
    TIERED_VOLUME = "TIERED_VOLUME"
    INCLUDED_UNITS = "INCLUDED_UNITS"
    DISCOUNT_PCT = "DISCOUNT_PCT"
    MINIMUM_COMMIT = "MINIMUM_COMMIT"


class InvoiceLine(Base):
    """
    One line item on the disputed invoice.
    original_amount_cents: what the customer was actually billed (integer cents).
    Primary key is scoped to (case_id, id) so multiple cases can use 'line-1' without collision.
    """
    __tablename__ = "invoice_lines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cases.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    original_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    case: Mapped["Case"] = relationship(back_populates="invoice_lines")  # noqa: F821
    contract_rules: Mapped[list["ContractRule"]] = relationship(
        back_populates="invoice_line",
        cascade="all, delete-orphan",
        primaryjoin="and_(InvoiceLine.case_id == ContractRule.case_id, InvoiceLine.id == ContractRule.line_id)",
        overlaps="contract_rules,case",
    )


class ContractRule(Base):
    """
    One pricing rule for one invoice line.
    Primary key is scoped to (case_id, id) so multiple cases can use 'rule-1' without collision.

    tiers: JSON list of {up_to: int|null, price_per_unit_cents: int}
    exempt_environments: JSON list of strings, e.g. ["staging"]
    discount_pct: stored as Numeric(7,4) — e.g. 10.0000 for 10%
    """
    __tablename__ = "contract_rules"
    __table_args__ = (
        ForeignKeyConstraint(
            ["case_id", "line_id"],
            ["invoice_lines.case_id", "invoice_lines.id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cases.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    line_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    rule_type: Mapped[str] = mapped_column(
        Enum(RuleTypeDB, name="rule_type_enum", create_constraint=True), nullable=False
    )
    rate_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tiers: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    discount_pct: Mapped[Optional[float]] = mapped_column(Numeric(7, 4), nullable=True)
    minimum_commit_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    included_units: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    overage_rate_cents: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    exempt_environments: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    supersedes_rule_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    case: Mapped["Case"] = relationship(back_populates="contract_rules", overlaps="contract_rules,invoice_line")  # noqa: F821
    invoice_line: Mapped["InvoiceLine"] = relationship(
        back_populates="contract_rules",
        primaryjoin="and_(ContractRule.case_id == InvoiceLine.case_id, ContractRule.line_id == InvoiceLine.id)",
        overlaps="case,contract_rules",
    )
