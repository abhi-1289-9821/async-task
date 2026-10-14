"""
routers/credits.py
==================
Endpoints for approving mock credits and viewing case credits.
Enforces concurrency locking, idempotency check, and cumulative cap verification.
"""

from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import AuthUser, get_current_user, require_reviewer
from app.models.calculation import Calculation, CalculationLineResult
from app.models.case import Case
from app.models.credit import Credit
from app.models.invoice import InvoiceLine
from app.schemas.credit import CreditApproveRequest, CreditCapResponse, CreditResponse
from app.services.credit_service import approve_credit, compute_remaining_cap


router = APIRouter(prefix="/api/credits", tags=["credits"])


@router.post("/approve", response_model=CreditResponse, status_code=status.HTTP_201_CREATED)
def approve_mock_credit(
    payload: CreditApproveRequest,
    user: Annotated[AuthUser, Depends(require_reviewer)],
    db: Session = Depends(get_db),
):
    """
    Approves a mock credit under row lock and cumulative cap checks.
    - Requires an accepted, non-stale finding.
    - Rejects duplicate idempotency keys with HTTP 409 Conflict.
    - Enforces cumulative credit cap.
    """
    return approve_credit(
        db=db,
        case_id=payload.case_id,
        invoice_line_id=payload.invoice_line_id,
        reason_code=payload.reason_code,
        finding_id=payload.finding_id,
        actor=user.identity,
        resolution_option_id=payload.resolution_option_id,
        requested_amount_cents=payload.requested_amount_cents,
        reason_note=payload.reason_note,
        client_idempotency_key=payload.idempotency_key,
    )


@router.post("/case/{case_id}", response_model=CreditResponse, status_code=status.HTTP_201_CREATED)
def approve_case_credit(
    case_id: str,
    payload: CreditApproveRequest,
    user: Annotated[AuthUser, Depends(require_reviewer)],
    db: Session = Depends(get_db),
):
    """Alias for POST /api/credits/approve with case_id in URL."""
    return approve_credit(
        db=db,
        case_id=case_id,
        invoice_line_id=payload.invoice_line_id,
        reason_code=payload.reason_code,
        finding_id=payload.finding_id,
        actor=user.identity,
        resolution_option_id=payload.resolution_option_id,
        requested_amount_cents=payload.requested_amount_cents,
        reason_note=payload.reason_note,
        client_idempotency_key=payload.idempotency_key,
    )


@router.get("/case/{case_id}/cap", response_model=CreditCapResponse)
def get_credit_cap(
    case_id: str,
    invoice_line_id: str = Query(..., description="Invoice line to compute cap for"),
    calculation_line_result_id: Optional[int] = Query(None, description="Specific line result (uses latest if omitted)"),
    user: Annotated[AuthUser, Depends(get_current_user)] = None,
    db: Session = Depends(get_db),
):
    """
    Returns the credit cap breakdown for a given invoice line.
    The frontend calls this endpoint instead of recomputing money in JavaScript.
    Uses the SAME logic as the approve_credit path.
    """
    case = db.query(Case).filter(Case.id == case_id).one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail=f"Case '{case_id}' not found")

    inv_line = db.query(InvoiceLine).filter(InvoiceLine.case_id == case_id, InvoiceLine.id == invoice_line_id).first()
    empty = CreditCapResponse(
        original_billed_cents=inv_line.original_amount_cents if inv_line else None,
        recalculated_cents=None,
        gross_discrepancy_cents=None,
        eligible_cents=0,
        prior_credits_cents=0,
        line_adjustments_cents=0,
        case_wide_adjustments_cents=0,
        unverified_adjustments_cents=0,
        remaining_cap_cents=0,
        issued_credit_cents=0,
        is_eligible=False,
        blocked_reason="No deterministic calculation run found for invoice line",
        currency=case.currency if case and case.currency else "USD",
    )

    if calculation_line_result_id:
        lr = db.query(CalculationLineResult).filter(CalculationLineResult.id == calculation_line_result_id).one_or_none()
    else:
        latest_calc = (
            db.query(Calculation)
            .filter(Calculation.case_id == case_id)
            .order_by(desc(Calculation.created_at), desc(Calculation.id))
            .first()
        )
        if not latest_calc:
            return empty
        lr = (
            db.query(CalculationLineResult)
            .filter(
                CalculationLineResult.calculation_id == latest_calc.id,
                CalculationLineResult.line_id == invoice_line_id,
            )
            .first()
        )

    if not lr:
        return empty

    cap_info = compute_remaining_cap(db, case_id, invoice_line_id, lr)
    return CreditCapResponse(**cap_info)


@router.get("/case/{case_id}", response_model=list[CreditResponse])
def list_case_credits(
    case_id: str,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Lists all approved credits for a case."""
    case = db.query(Case).filter(Case.id == case_id).one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail=f"Case '{case_id}' not found")

    return db.query(Credit).filter(Credit.case_id == case_id).order_by(Credit.created_at.desc()).all()
