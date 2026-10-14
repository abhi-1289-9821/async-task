"""
models/investigation.py
========================
InvestigationRun, Finding, FindingReview, and ResolutionOption tables.

InvestigationRun: one LangGraph graph execution.
  - Status: RUNNING / COMPLETED / PARTIAL / FAILED / BLOCKED / DISCARDED
  - BLOCKED: gather_evidence found no valid calculation (does NOT create a Finding)
  - DISCARDED: new evidence arrived while this run was executing; result is invalid
  - evidence_version + calculation_id bind this run to specific inputs

Finding: structured AI output for one investigation run.
  - finding_type: CONFIRMED_CALCULATION_DISCREPANCY / POSSIBLE_DISCREPANCY /
                  CONTRACT_AMBIGUITY / INSUFFICIENT_EVIDENCE / NO_DISCREPANCY / UNRESOLVED
  - is_stale: True after new evidence arrives; stale findings cannot be used for credit approval
  - All text fields are the RAW AI output — never modified.

FindingReview: human review of a finding (ACCEPT / EDIT / REJECT).
  - ai_text preserved; edited_text stored separately.
  - Credit approval requires an ACCEPTED, non-stale finding/option.

ResolutionOption: one proposed action from the agent.
  - option_type: REQUEST_EVIDENCE / ESCALATE / CORRECT_INVOICE /
                 RECOMMEND_CREDIT / CLOSE_NO_ADJUSTMENT
  - calculation_line_result_id: the ONLY source of the credit amount.
    The amount is FETCHED from the DB by this ID; never trusted from LLM output.
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
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class RunStatus(str, enum.Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"      # LLM failure on one node; deterministic results preserved
    FAILED = "FAILED"        # Complete failure
    BLOCKED = "BLOCKED"      # No valid calculation available; no findings created
    DISCARDED = "DISCARDED"  # Evidence changed while running; results must not be used


class AgentFindingType(str, enum.Enum):
    CONFIRMED_CALCULATION_DISCREPANCY = "CONFIRMED_CALCULATION_DISCREPANCY"
    POSSIBLE_DISCREPANCY = "POSSIBLE_DISCREPANCY"
    CONTRACT_AMBIGUITY = "CONTRACT_AMBIGUITY"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    NO_DISCREPANCY = "NO_DISCREPANCY"
    UNRESOLVED = "UNRESOLVED"


class OptionType(str, enum.Enum):
    REQUEST_EVIDENCE = "REQUEST_EVIDENCE"
    ESCALATE = "ESCALATE"
    CORRECT_INVOICE = "CORRECT_INVOICE"
    RECOMMEND_CREDIT = "RECOMMEND_CREDIT"
    CLOSE_NO_ADJUSTMENT = "CLOSE_NO_ADJUSTMENT"
    CREDIT_UNDISPUTED_PORTION = "CREDIT_UNDISPUTED_PORTION"


class ReviewDecision(str, enum.Enum):
    ACCEPT = "ACCEPT"
    EDIT = "EDIT"
    REJECT = "REJECT"


class InvestigationRun(Base):
    __tablename__ = "investigation_runs"
    __table_args__ = (
        Index(
            "ix_one_running_investigation_per_case",
            "case_id",
            unique=True,
            postgresql_where=text("status = 'RUNNING'"),
            sqlite_where=text("status = 'RUNNING'"),
        ),
    )


    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    calculation_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("calculations.id", ondelete="SET NULL"), nullable=True
    )
    evidence_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(RunStatus, name="run_status_enum", create_constraint=True),
        nullable=False, default=RunStatus.RUNNING.value
    )
    status_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_usage: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    case: Mapped["Case"] = relationship(back_populates="investigation_runs")  # noqa: F821
    calculation: Mapped[Optional["Calculation"]] = relationship(back_populates="investigation_runs")  # noqa: F821
    findings: Mapped[list["Finding"]] = relationship(
        back_populates="investigation_run", cascade="all, delete-orphan"
    )
    resolution_options: Mapped[list["ResolutionOption"]] = relationship(
        back_populates="investigation_run", cascade="all, delete-orphan"
    )


class Finding(Base):
    """
    One AI finding from an investigation run.
    All text is the raw AI output — never modified after creation.
    """
    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("investigation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    finding_type: Mapped[str] = mapped_column(
        Enum(AgentFindingType, name="agent_finding_type_enum", create_constraint=True), nullable=False
    )
    narrative: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_ai_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    calculation_line_result_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("calculation_line_results.id", ondelete="SET NULL"), nullable=True
    )
    # Structured AI outputs — stored separately for clarity
    verified_facts: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    possible_explanations: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    assumptions: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    open_questions: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    missing_evidence_questions: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    citation_ids: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)  # evidence/result IDs cited
    citation_validation_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    consistency_check_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    validation_notes: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    # Staleness tracking
    is_stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    stale_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    investigation_run: Mapped["InvestigationRun"] = relationship(back_populates="findings")
    reviews: Mapped[list["FindingReview"]] = relationship(
        back_populates="finding",
        cascade="all, delete-orphan",
        order_by="FindingReview.created_at.desc(), FindingReview.id.desc()",
    )


class FindingReview(Base):
    """
    Human review of a finding. Preserves original AI text; stores edits separately.
    Credit approval requires action=ACCEPT on a non-stale finding.
    """
    __tablename__ = "finding_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    finding_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("findings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(
        Enum(ReviewDecision, name="review_decision_enum", create_constraint=True), nullable=False
    )
    reviewer: Mapped[str] = mapped_column(String(50), nullable=False)  # "REVIEWER" identity
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    original_ai_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    edited_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # separate from AI text
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    @property
    def reviewed_at(self) -> datetime:
        return self.created_at

    finding: Mapped["Finding"] = relationship(back_populates="reviews")




class ResolutionOption(Base):
    """
    One proposed action from the agent.
    Amount (if RECOMMEND_CREDIT) is always fetched from calculation_line_result_id.
    The LLM does NOT provide the amount; it only references the result ID.
    """
    __tablename__ = "resolution_options"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("investigation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    option_type: Mapped[str] = mapped_column(
        Enum(OptionType, name="option_type_enum", create_constraint=True), nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    calculation_line_result_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("calculation_line_results.id", ondelete="SET NULL"), nullable=True
    )
    is_stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    stale_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    investigation_run: Mapped["InvestigationRun"] = relationship(back_populates="resolution_options")
    calculation_line_result: Mapped[Optional["CalculationLineResult"]] = relationship(  # noqa: F821
        back_populates="resolution_options"
    )
    credits: Mapped[list["Credit"]] = relationship(back_populates="resolution_option")  # noqa: F821
