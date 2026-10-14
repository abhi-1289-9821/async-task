"""
models/calculation.py
=====================
Calculation and CalculationLineResult tables.

Calculation: one billing engine run. Immutable after creation.
  - Bound to an evidence_version to detect staleness.
  - result_hash: the engine's own deterministic hash of its inputs (from EngineResult).
  - engine_status: OK / AMBIGUOUS / INSUFFICIENT_DATA / PARTIAL

CalculationLineResult: one row per invoice line per calculation.
  - result_id: the deterministic ID from the engine (used in citation validation).
  - finding_type: engine-level finding (not AI finding).
  - interpretations: JSON list for AMBIGUOUS lines.
  - Immutable: never updated after creation.
"""

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
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


class EngineStatusDB(str, enum.Enum):
    OK = "OK"
    AMBIGUOUS = "AMBIGUOUS"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    PARTIAL = "PARTIAL"


class FindingTypeDB(str, enum.Enum):
    CONFIRMED_CALCULATION_DISCREPANCY = "CONFIRMED_CALCULATION_DISCREPANCY"
    NO_DISCREPANCY = "NO_DISCREPANCY"
    AMBIGUOUS = "AMBIGUOUS"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class Calculation(Base):
    """
    One complete billing engine run for a case.
    Immutable after creation.
    """
    __tablename__ = "calculations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    evidence_version: Mapped[int] = mapped_column(Integer, nullable=False)
    engine_status: Mapped[str] = mapped_column(
        Enum(EngineStatusDB, name="engine_status_enum", create_constraint=True), nullable=False
    )
    engine_status_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    total_original_billed_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    total_recalculated_cents: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_difference_cents: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    result_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    quarantined_events: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    case: Mapped["Case"] = relationship(back_populates="calculations")  # noqa: F821
    line_results: Mapped[list["CalculationLineResult"]] = relationship(
        back_populates="calculation", cascade="all, delete-orphan"
    )
    investigation_runs: Mapped[list["InvestigationRun"]] = relationship(  # noqa: F821
        back_populates="calculation"
    )


class CalculationLineResult(Base):
    """
    Engine result for one invoice line within one calculation.
    Immutable. result_id is the deterministic ID from the engine — used as citation anchor.
    """
    __tablename__ = "calculation_line_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    calculation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("calculations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    line_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    result_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)  # "res_" + 16 hex chars
    rule_id: Mapped[str] = mapped_column(String(36), nullable=False)
    original_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    recalculated_amount_cents: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    difference_cents: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    finding_type: Mapped[str] = mapped_column(
        Enum(FindingTypeDB, name="finding_type_db_enum", create_constraint=True), nullable=False
    )
    quantity_used: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    exempt_quantity: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    applied_discount_pct: Mapped[Optional[float]] = mapped_column(Numeric(7, 4), nullable=True)
    applied_minimum_commit_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    interpretations: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)  # for AMBIGUOUS
    assumptions: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    quarantined_events: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    undisputed_overcharge_cents: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    calculation: Mapped["Calculation"] = relationship(back_populates="line_results")
    resolution_options: Mapped[list["ResolutionOption"]] = relationship(  # noqa: F821
        back_populates="calculation_line_result"
    )
