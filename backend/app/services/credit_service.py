"""
services/credit_service.py
==========================
Concurrency-safe, idempotent mock credit approval service.

Guarantees:
  1. Concurrency Locking:
     - PostgreSQL: SELECT FOR UPDATE on target Case and InvoiceLine rows.
     - SQLite: BEGIN IMMEDIATE transaction serialization with fallback.
  2. Idempotency:
     - Idempotency key = client_idempotency_key or SHA-256(case_id + invoice_line_id + reason_code).
     - Existing record with identical key raises HTTP 409 Conflict.
     - Database-level unique constraint collision is caught via IntegrityError.
  3. Preconditions:
     - Requires an accepted, non-stale finding review (action == "ACCEPT").
     - Rejects stale findings with HTTP 400.
  4. Amount Safety & Cumulative Cap:
     - Amount derived from deterministic calculation_line_result_id (never from LLM).
     - Enforces: requested_amount <= (eligible_overcharge - prior_credits - adjustments).
     - Cap breach raises HTTP 400.
"""

import hashlib
import uuid
from typing import Optional
from fastapi import HTTPException, status
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.models.case import Case, CaseEvent
from app.models.invoice import InvoiceLine
from app.models.investigation import Finding, FindingReview, ResolutionOption
from app.models.calculation import CalculationLineResult
from app.models.credit import Credit, Adjustment


def generate_idempotency_key(
    case_id: str,
    invoice_line_id: str,
    reason_code: str,
    custom_key: Optional[str] = None,
) -> str:
    """Computes SHA-256 idempotency key or returns client-provided key."""
    if custom_key:
        return custom_key
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
    requested_amount_cents: Optional[int] = None,
    reason_note: Optional[str] = None,
    client_idempotency_key: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> Credit:
    """
    Approves a mock credit under row-level lock and cumulative cap checks.
    """
    is_postgres = db.bind is not None and db.bind.dialect.name == "postgresql"

    # ── 1. Concurrency Locking ──────────────────────────────────────────────────
    if is_postgres:
        # Lock both the Case row and the InvoiceLine row in PostgreSQL
        # Prevents concurrent evidence upload (which bumps version & marks stale)
        case = (
            db.query(Case)
            .filter(Case.id == case_id)
            .with_for_update()
            .one_or_none()
        )
        line = (
            db.query(InvoiceLine)
            .filter(InvoiceLine.id == invoice_line_id, InvoiceLine.case_id == case_id)
            .with_for_update()
            .one_or_none()
        )
    else:
        # SQLite: serialize transactions via BEGIN IMMEDIATE if not already begun
        try:
            db.execute(text("BEGIN IMMEDIATE;"))
        except OperationalError as e:
            if "cannot start a transaction within a transaction" not in str(e).lower():
                raise

        case = db.query(Case).filter(Case.id == case_id).one_or_none()
        line = (
            db.query(InvoiceLine)
            .filter(InvoiceLine.id == invoice_line_id, InvoiceLine.case_id == case_id)
            .one_or_none()
        )

    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case '{case_id}' not found",
        )

    if not line:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invoice line '{invoice_line_id}' not found for case '{case_id}'",
        )

    # ── 2. Idempotency Check ────────────────────────────────────────────────────
    idempotency_key = generate_idempotency_key(
        case_id, invoice_line_id, reason_code, client_idempotency_key
    )
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

    # Invariant: Only confirmed calculation discrepancies can receive credit approvals
    if finding.finding_type != "CONFIRMED_CALCULATION_DISCREPANCY":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Credit approval requires finding type CONFIRMED_CALCULATION_DISCREPANCY, "
                f"but finding is '{finding.finding_type}'"
            ),
        )

    # Check that the LATEST human review is ACCEPT (prevent ACCEPT-then-REJECT payment bug)
    latest_review = (
        db.query(FindingReview)
        .filter(FindingReview.finding_id == finding_id)
        .order_by(FindingReview.created_at.desc(), FindingReview.id.desc())
        .first()
    )
    if not latest_review or latest_review.action != "ACCEPT":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Credit approval requires an accepted human finding review "
                f"(latest review action must be 'ACCEPT', but was '{latest_review.action if latest_review else 'NONE'}')"
            ),
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

    # Invariant: Calculation line result must also be CONFIRMED_CALCULATION_DISCREPANCY
    lr_finding_type = line_result.finding_type.value if hasattr(line_result.finding_type, "value") else str(line_result.finding_type)
    if lr_finding_type != "CONFIRMED_CALCULATION_DISCREPANCY":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Credit approval requires calculation line result finding type CONFIRMED_CALCULATION_DISCREPANCY, "
                f"but line result is '{lr_finding_type}'"
            ),
        )

    # Invariant: Line in calculation result must match the requested invoice_line_id
    if line_result.line_id != invoice_line_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Invoice line mismatch: finding calculation result is for line '{line_result.line_id}', "
                f"but credit was requested for line '{invoice_line_id}'"
            ),
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

    # Prior adjustments for this line (either explicitly linked to this line, or case-wide)
    line_adjustments = (
        db.query(func.coalesce(func.sum(Adjustment.amount_cents), 0))
        .filter(
            Adjustment.case_id == case_id,
            (Adjustment.invoice_line_id == invoice_line_id) | (Adjustment.invoice_line_id.is_(None)),
        )
        .scalar()
    )

    remaining_cap = eligible_overcharge - prior_credits - line_adjustments
    if remaining_cap <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Cumulative credit cap reached for line '{invoice_line_id}'. "
                f"Eligible overcharge: {eligible_overcharge}¢, Prior credits: {prior_credits}¢, "
                f"Adjustments: {line_adjustments}¢. Remaining cap: {remaining_cap}¢."
            ),
        )

    # Determine amount to credit: respect requested amount or default to remaining cap
    if requested_amount_cents is not None:
        if requested_amount_cents <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Requested credit amount must be greater than zero",
            )
        if requested_amount_cents > remaining_cap:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Requested credit amount ({requested_amount_cents}¢) exceeds remaining cap ({remaining_cap}¢)"
                ),
            )
        amount_to_credit = requested_amount_cents
    else:
        amount_to_credit = remaining_cap

    # ── 5. Record Approved Credit & Catch Concurrent Integrity Collisions ───────
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

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Handle race condition where two requests bypassed the exists check simultaneously
        existing = db.query(Credit).filter(Credit.idempotency_key == idempotency_key).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Credit already approved with idempotency key {idempotency_key}",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Database integrity constraint collision during credit approval",
        )

    db.refresh(credit)
    return credit
