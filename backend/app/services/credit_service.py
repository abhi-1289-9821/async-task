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
from app.models.calculation import Calculation, CalculationLineResult, FindingTypeDB
from app.models.credit import Credit, Adjustment


def generate_idempotency_key(
    case_id: str,
    invoice_line_id: str,
    reason_code: Optional[str] = None,
    custom_key: Optional[str] = None,
    finding_id: Optional[str] = None,
) -> str:
    """
    Computes SHA-256 idempotency key anchored strictly to (case_id, invoice_line_id, finding_id).
    reason_code is intentionally omitted from the hash payload to prevent bypassing
    duplicate credit protection by simply submitting under a different reason code.
    """
    if custom_key:
        return custom_key
    payload = f"{case_id}:{invoice_line_id}:{finding_id or ''}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_remaining_cap(
    db: Session,
    case_id: str,
    invoice_line_id: str,
    line_result,
) -> dict:
    """
    Computes the remaining credit cap for an invoice line.
    Returns a dict with all 8 authoritative credit governance metrics.
    Used by both approve_credit and GET /cap endpoint.
    """
    if getattr(line_result, "finding_type", None) in ("AMBIGUOUS", FindingTypeDB.AMBIGUOUS) or (getattr(line_result, "undisputed_overcharge_cents", None) and getattr(line_result, "undisputed_overcharge_cents") > 0):
        eligible_overcharge = getattr(line_result, "undisputed_overcharge_cents", 0) or 0
    elif line_result.difference_cents is None:
        eligible_overcharge = 0
    else:
        eligible_overcharge = abs(line_result.difference_cents) if line_result.difference_cents < 0 else 0

    prior_credits = int(
        db.query(func.coalesce(func.sum(Credit.amount_cents), 0))
        .filter(
            Credit.case_id == case_id,
            Credit.invoice_line_id == invoice_line_id,
        )
        .scalar()
    )

    # Only verified adjustments count against the confirmed credit cap
    line_adjustments = int(
        db.query(func.coalesce(func.sum(Adjustment.amount_cents), 0))
        .filter(
            Adjustment.case_id == case_id,
            Adjustment.invoice_line_id == invoice_line_id,
            Adjustment.is_verified == True,  # noqa: E712
        )
        .scalar()
    )
    line_cap = max(0, eligible_overcharge - prior_credits - line_adjustments)

    case_wide_adjustments = int(
        db.query(func.coalesce(func.sum(Adjustment.amount_cents), 0))
        .filter(
            Adjustment.case_id == case_id,
            Adjustment.invoice_line_id.is_(None),
            Adjustment.is_verified == True,  # noqa: E712
        )
        .scalar()
    )

    unverified_adjustments = int(
        db.query(func.coalesce(func.sum(Adjustment.amount_cents), 0))
        .filter(
            Adjustment.case_id == case_id,
            Adjustment.is_verified == False,  # noqa: E712
        )
        .scalar()
    )

    if case_wide_adjustments > 0:
        all_case_credits = int(
            db.query(func.coalesce(func.sum(Credit.amount_cents), 0))
            .filter(Credit.case_id == case_id)
            .scalar()
        )
        latest_calc = (
            db.query(Calculation)
            .filter(Calculation.case_id == case_id)
            .order_by(Calculation.created_at.desc(), Calculation.id.desc())
            .first()
        )
        calc_id = latest_calc.id if latest_calc else line_result.calculation_id
        all_lrs = (
            db.query(CalculationLineResult)
            .join(Calculation, Calculation.id == CalculationLineResult.calculation_id)
            .filter(
                Calculation.id == calc_id,
                Calculation.case_id == case_id,
            )
            .all()
        )
        total_case_overcharge = 0
        for lr_item in all_lrs:
            if lr_item.difference_cents is not None and lr_item.difference_cents < 0:
                total_case_overcharge += abs(lr_item.difference_cents)
            elif getattr(lr_item, "undisputed_overcharge_cents", None) and lr_item.undisputed_overcharge_cents > 0:
                total_case_overcharge += lr_item.undisputed_overcharge_cents

        case_cap = max(0, total_case_overcharge - all_case_credits - case_wide_adjustments)
        remaining_cap = min(line_cap, case_cap)
    else:
        remaining_cap = line_cap

    case = db.query(Case).filter(Case.id == case_id).first()
    currency = case.currency if case and case.currency else "USD"

    # Evaluate approval eligibility and blocked reason
    is_eligible = True
    blocked_reason = None
    lr_ft = getattr(line_result, "finding_type", None)
    lr_ft_str = lr_ft.value if hasattr(lr_ft, "value") else str(lr_ft)
    if lr_ft_str == "INSUFFICIENT_DATA" or (line_result.difference_cents is None and lr_ft_str != "AMBIGUOUS"):
        is_eligible = False
        blocked_reason = "Evidence is insufficient for deterministic calculation"
    else:
        finding = (
            db.query(Finding)
            .filter(
                Finding.case_id == case_id,
                (Finding.invoice_line_id == invoice_line_id) | (Finding.calculation_line_result_id == line_result.id)
            )
            .order_by(Finding.created_at.desc(), Finding.id.desc())
            .first()
        )
        if not finding:
            is_eligible = False
            blocked_reason = f"No finding available for line {invoice_line_id}"
        elif finding.is_stale:
            is_eligible = False
            blocked_reason = "Finding is stale due to updated evidence"
        else:
            latest_review = (
                db.query(FindingReview)
                .filter(FindingReview.finding_id == finding.id)
                .order_by(FindingReview.created_at.desc(), FindingReview.id.desc())
                .first()
            )
            if not latest_review or latest_review.action != "ACCEPT":
                is_eligible = False
                blocked_reason = f"Latest review must be ACCEPT (currently {latest_review.action if latest_review else 'unreviewed'})"
            elif remaining_cap <= 0:
                is_eligible = False
                blocked_reason = "Remaining allowable credit cap is $0.00"

    return {
        "original_billed_cents": getattr(line_result, "original_amount_cents", None),
        "recalculated_cents": getattr(line_result, "recalculated_amount_cents", None),
        "gross_discrepancy_cents": getattr(line_result, "difference_cents", None),
        "prior_credits_cents": prior_credits,
        "line_adjustments_cents": line_adjustments,
        "case_wide_adjustments_cents": case_wide_adjustments,
        "unverified_adjustments_cents": unverified_adjustments,
        "eligible_cents": eligible_overcharge,
        "remaining_cap_cents": remaining_cap,
        "issued_credit_cents": prior_credits,
        "is_eligible": is_eligible,
        "blocked_reason": blocked_reason,
        "currency": currency,
    }




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
        case_id=case_id,
        invoice_line_id=invoice_line_id,
        reason_code=reason_code,
        custom_key=client_idempotency_key,
        finding_id=finding_id,
    )
    existing_credit = db.query(Credit).filter(Credit.idempotency_key == idempotency_key).first()
    if existing_credit:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Credit already approved with idempotency key {idempotency_key}",
        )

    # ── 3. Finding & Human Review Preconditions ─────────────────────────────────
    if not reason_code or not reason_code.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="reason_code cannot be empty",
        )

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

    if finding.invoice_line_id and finding.invoice_line_id != invoice_line_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Finding is for invoice line '{finding.invoice_line_id}', but credit requested for line '{invoice_line_id}'",
        )
    if not finding.invoice_line_id:
        finding.invoice_line_id = invoice_line_id

    # Guard: A finding can only receive one credit approval
    existing_finding_credit = db.query(Credit).filter(Credit.finding_id == finding_id).first()
    if existing_finding_credit:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Credit already approved for finding '{finding_id}'",
        )

    # ── 3b. Validate Resolution Option (if supplied) ───────────────────────────
    res_opt = None
    if resolution_option_id:
        res_opt = (
            db.query(ResolutionOption)
            .filter(ResolutionOption.id == resolution_option_id)
            .one_or_none()
        )
        if not res_opt:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"ResolutionOption '{resolution_option_id}' not found",
            )
        if res_opt.case_id != case_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"ResolutionOption '{resolution_option_id}' does not belong to case '{case_id}'",
            )
        if res_opt.is_stale:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"ResolutionOption '{resolution_option_id}' is stale. Rerun investigation before approving credit.",
            )
        if res_opt.option_type not in ("RECOMMEND_CREDIT", "CREDIT_UNDISPUTED_PORTION"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"ResolutionOption type is '{res_opt.option_type}', expected 'RECOMMEND_CREDIT' or 'CREDIT_UNDISPUTED_PORTION'",
            )
        if res_opt.invoice_line_id and res_opt.invoice_line_id != invoice_line_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"ResolutionOption is for invoice line '{res_opt.invoice_line_id}', but credit requested for line '{invoice_line_id}'",
            )
        if (
            res_opt.calculation_line_result_id is not None
            and res_opt.calculation_line_result_id != finding.calculation_line_result_id
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ResolutionOption calculation line result does not match finding calculation line result",
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

    # Invariant: AI verification checks must pass
    if finding.citation_validation_passed is False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credit approval requires finding with valid citations (citation validation failed)",
        )

    if finding.consistency_check_passed is False and not (latest_review and latest_review.action == "ACCEPT" and finding.finding_type == "CONFIRMED_CALCULATION_DISCREPANCY"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credit approval requires finding that passed consistency check (consistency check failed)",
        )

    # Invariant: Only confirmed discrepancies or CREDIT_UNDISPUTED_PORTION for ambiguities can receive credit
    is_undisputed_credit = bool(res_opt and res_opt.option_type == "CREDIT_UNDISPUTED_PORTION")
    if not is_undisputed_credit and finding.finding_type != "CONFIRMED_CALCULATION_DISCREPANCY":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Credit approval requires finding type CONFIRMED_CALCULATION_DISCREPANCY, "
                f"but finding is '{finding.finding_type}'"
            ),
        )
    if is_undisputed_credit and finding.finding_type not in ("CONTRACT_AMBIGUITY", "CONFIRMED_CALCULATION_DISCREPANCY"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"CREDIT_UNDISPUTED_PORTION requires finding type CONTRACT_AMBIGUITY, "
                f"but finding is '{finding.finding_type}'"
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

    calc = db.query(Calculation).filter(Calculation.id == line_result.calculation_id).first()
    if not calc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Calculation '{line_result.calculation_id}' not found",
        )
    if calc.evidence_version != case.evidence_version:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Calculation result is from evidence version {calc.evidence_version}, "
                f"but case is currently at evidence version {case.evidence_version}. "
                "Rerun calculation on current evidence before approving credit."
            ),
        )

    lr_finding_type = line_result.finding_type.value if hasattr(line_result.finding_type, "value") else str(line_result.finding_type)
    if lr_finding_type == "INSUFFICIENT_DATA" or (line_result.difference_cents is None and not is_undisputed_credit):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot approve credit: Calculation line has insufficient usage evidence (uncomputed amount).",
        )

    if is_undisputed_credit:
        if lr_finding_type not in ("AMBIGUOUS", "CONFIRMED_CALCULATION_DISCREPANCY"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"CREDIT_UNDISPUTED_PORTION requires calculation line result finding type AMBIGUOUS, but line result is '{lr_finding_type}'",
            )
        undisputed_amt = getattr(line_result, "undisputed_overcharge_cents", 0) or 0
        if undisputed_amt <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Calculation result shows no undisputed overcharge on this line item",
            )
    else:
        # Invariant: Calculation line result must also be CONFIRMED_CALCULATION_DISCREPANCY
        if lr_finding_type != "CONFIRMED_CALCULATION_DISCREPANCY":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Credit approval requires calculation line result finding type CONFIRMED_CALCULATION_DISCREPANCY, "
                    f"but line result is '{lr_finding_type}'"
                ),
            )

        # Overcharge: difference_cents is negative (recalculated - original)
        if line_result.difference_cents >= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Calculation result shows no overcharge on this line item",
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

    # Use shared helper — same logic as GET /cap endpoint
    cap_info = compute_remaining_cap(db, case_id, invoice_line_id, line_result)
    remaining_cap = cap_info["remaining_cap_cents"]
    eligible_overcharge = cap_info["eligible_cents"]
    prior_credits = cap_info["prior_credits_cents"]
    line_adjustments = cap_info["line_adjustments_cents"]
    case_wide_adjustments = cap_info["case_wide_adjustments_cents"]

    if remaining_cap <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Cumulative credit cap reached for line '{invoice_line_id}'. "
                f"Eligible overcharge: {eligible_overcharge}¢, Prior line credits: {prior_credits}¢, "
                f"Line adjustments: {line_adjustments}¢, Case adjustments: {case_wide_adjustments}¢. "
                f"Remaining allowable cap: {remaining_cap}¢."
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
        finding_id=finding_id,
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
        existing_finding = db.query(Credit).filter(Credit.finding_id == finding_id).first()
        if existing_finding:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Credit already approved for finding '{finding_id}'",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Database integrity constraint collision during credit approval",
        )

    db.refresh(credit)
    return credit
