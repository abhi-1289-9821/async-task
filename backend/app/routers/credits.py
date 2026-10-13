"""
routers/credits.py
==================
Endpoints for approving mock credits and viewing case credits.
Enforces concurrency locking, idempotency check, and cumulative cap verification.
"""

from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import AuthUser, get_current_user, require_reviewer
from app.models.case import Case
from app.models.credit import Credit
from app.schemas.credit import CreditApproveRequest, CreditResponse
from app.services.credit_service import approve_credit


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
