"""
routers/findings.py
===================
Endpoints for retrieving findings and submitting human reviews (ACCEPT, EDIT, REJECT).
Preserves original AI generated text while capturing human edits and rationale separately.
"""

from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import AuthUser, get_current_user, require_reviewer
from app.models.case import Case, CaseEvent
from app.models.investigation import Finding, FindingReview
from app.schemas.investigation import (
    FindingResponse,
    FindingReviewRequest,
    FindingReviewResponse,
)


router = APIRouter(prefix="/api/findings", tags=["findings"])


@router.get("/case/{case_id}", response_model=list[FindingResponse])
def list_case_findings(
    case_id: str,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Lists all findings for a given case, including their staleness status and reviews."""
    case = db.query(Case).filter(Case.id == case_id).one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail=f"Case '{case_id}' not found")

    return db.query(Finding).filter(Finding.case_id == case_id).order_by(Finding.created_at.desc()).all()


@router.post("/{id}/review", response_model=FindingReviewResponse, status_code=status.HTTP_201_CREATED)
def review_finding(
    id: str,
    payload: FindingReviewRequest,
    user: Annotated[AuthUser, Depends(require_reviewer)],
    db: Session = Depends(get_db),
):
    """
    Submits a human review for an AI finding: ACCEPT, EDIT, or REJECT.
    - Preserves the original AI text permanently.
    - Captures the reviewer's edits and note separately.
    - Records an append-only audit event in case_events.
    """
    finding = db.query(Finding).filter(Finding.id == id).one_or_none()
    if not finding:
        raise HTTPException(status_code=404, detail=f"Finding '{id}' not found")

    if finding.is_stale:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Finding '{id}' is stale due to new evidence ({finding.stale_reason or 'evidence changed'}). Re-run the investigation before submitting a review.",
        )

    if payload.action == "EDIT" and not payload.edited_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="edited_text is required when action is 'EDIT'",
        )

    review = FindingReview(
        finding_id=finding.id,
        reviewer=user.identity,
        action=payload.action,
        note=payload.note,
        original_ai_text=finding.raw_ai_text,
        edited_text=payload.edited_text if payload.action == "EDIT" else None,
    )
    db.add(review)

    # Append-only audit log
    event = CaseEvent(
        case_id=finding.case_id,
        event_type="FINDING_REVIEWED",
        actor=user.identity,
        details={
            "finding_id": finding.id,
            "action": payload.action,
            "note": payload.note,
            "has_edits": bool(payload.edited_text),
        },
    )
    db.add(event)

    db.commit()
    db.refresh(review)
    return review
