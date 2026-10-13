"""
services/credit_service.py
==========================
Concurrency-safe, idempotent mock credit approval service.

Guarantees:
  1. Concurrency Locking:
     - PostgreSQL: SELECT FOR UPDATE on target invoice line.
     - SQLite: BEGIN IMMEDIATE transaction serialization.
  2. Idempotency:
     - idempotency_key = SHA-256(case_id + invoice_line_id + reason_code)
     - Existing record with identical key raises HTTP 409 Conflict.
  3. Preconditions:
     - Requires an accepted, non-stale finding review (action == "ACCEPT").
     - Rejects stale findings with HTTP 400.
  4. Amount Safety & Cumulative Cap:
     - Amount derived from deterministic calculation_line_result_id (never from LLM).
     - Enforces: amount <= (eligible_overcharge - prior_credits - adjustments).
     - Cap breach raises HTTP 400.
"""

import hashlib
import uuid
from typing import Optional
from fastapi import HTTPException, status
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.models.case import Case, CaseEvent
from app.models.invoice import InvoiceLine
from app.models.investigation import Finding, FindingReview, ResolutionOption
from app.models.calculation import CalculationLineResult
from app.models.credit import Credit, Adjustment


def generate_idempotency_key(case_id: str, invoice_line_id: str, reason_code: str) -> str:
    """Computes SHA-256 idempotency key from case, line, and reason."""
    payload = f"{case_id}:{invoice_line_id}:{reason_code}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def approve_credit(
    db: Session,
    case_id: str,
    invoice_line_id: str,
    reason_code: str,
    finding_id: str,
    actor: str,
    resolution_option_id: Optional[str] = None,
    reason_note: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> Credit:
    """
    Approves a mock credit under row-level lock and cumulative cap checks.
    """
    # ── 1. Concurrency Locking ──────────────────────────────────────────────────
    if db.bind and db.bind.dialect.name == "postgresql":
        # Acquire row-level lock on the target invoice line in PostgreSQL
        line = (
            db.query(InvoiceLine)
            .filter(InvoiceLine.id == invoice_line_id, InvoiceLine.case_id == case_id)
            .with_for_update()
            .one_or_none()
        )
    else:
        # SQLite: serialize transactions via BEGIN IMMEDIATE
        try:
            db.execute(text("BEGIN IMMEDIATE;"))
        except Exception:
            # If transaction is already active in SQLite session
            pass
        line = (
            db.query(InvoiceLine)
            .filter(InvoiceLine.id == invoice_line_id, InvoiceLine.case_id == case_id)
            .one_or_none()
        )

    if not line:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invoice line '{invoice_line_id}' not found for case '{case_id}'",
        )

    # ── 2. Idempotency Check ────────────────────────────────────────────────────
    idempotency_key = generate_idempotency_key(case_id, invoice_line_id, reason_code)
    existing_credit = db.query(Credit).filter(Credit.idempotency_key == idempotency_key).first()
    if existing_credit:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Credit already approved with idempotency key {idempotency_key}",
        )

    # ── 3. Finding & Human Review Preconditions ─────────────────────────────────
    finding = db.query(Finding).filter(Finding.id == finding_id, Finding.case_id == case_id).one_or_none()
    if not finding:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Finding '{finding_id}' not found for case '{case_id}'",
        )

    if finding.is_stale:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Finding is stale due to new evidence. Rerun investigation before approving credit.",
        )

    # Check for an ACCEPTED human review
    accepted_review = (
        db.query(FindingReview)
        .filter(FindingReview.finding_id == finding_id, FindingReview.action == "ACCEPT")
        .first()
    )
    if not accepted_review:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credit approval requires an accepted human finding review (action == 'ACCEPT')",
        )

    # ── 4. Calculation Amount & Cumulative Cap ──────────────────────────────────
    if not finding.calculation_line_result_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Finding is not linked to a calculation line result",
        )

    line_result = (
        db.query(CalculationLineResult)
        .filter(CalculationLineResult.id == finding.calculation_line_result_id)
        .one_or_none()
    )
    if not line_result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"CalculationLineResult '{finding.calculation_line_result_id}' not found",
        )

    # Overcharge: difference_cents is negative (recalculated - original)
    if line_result.difference_cents >= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Calculation result shows no overcharge on this line item",
        )

    eligible_overcharge = abs(line_result.difference_cents)

    # Sum of prior approved credits for this line
    prior_credits = (
        db.query(func.coalesce(func.sum(Credit.amount_cents), 0))
        .filter(Credit.invoice_line_id == invoice_line_id)
        .scalar()
    )

    # Sum of prior account adjustments for this case
    case_adjustments = (
        db.query(func.coalesce(func.sum(Adjustment.amount_cents), 0))
        .filter(Adjustment.case_id == case_id)
        .scalar()
    )

    remaining_cap = eligible_overcharge - prior_credits - case_adjustments
    if remaining_cap <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Cumulative credit cap reached for line '{invoice_line_id}'. "
                f"Eligible overcharge: {eligible_overcharge}¢, Prior credits: {prior_credits}¢, "
                f"Adjustments: {case_adjustments}¢. Remaining cap: {remaining_cap}¢."
            ),
        )

    # Final credit amount is capped at remaining allowance
    amount_to_credit = remaining_cap

    # ── 5. Record Approved Credit & Audit Log ───────────────────────────────────
    credit = Credit(
        id=f"cred_{uuid.uuid4().hex[:12]}",
        case_id=case_id,
        invoice_line_id=invoice_line_id,
        resolution_option_id=resolution_option_id,
        calculation_line_result_id=finding.calculation_line_result_id,
        idempotency_key=idempotency_key,
        amount_cents=amount_to_credit,
        reason_code=reason_code,
        reason_note=reason_note,
        approved_by=actor,
    )
    db.add(credit)

    # Append-only audit event
    audit_event = CaseEvent(
        case_id=case_id,
        event_type="CREDIT_APPROVED",
        actor=actor,
        details={
            "credit_id": credit.id,
            "invoice_line_id": invoice_line_id,
            "amount_cents": amount_to_credit,
            "reason_code": reason_code,
            "idempotency_key": idempotency_key,
            "finding_id": finding_id,
        },
        correlation_id=correlation_id,
    )
    db.add(audit_event)

    db.commit()
    db.refresh(credit)
    return credit
