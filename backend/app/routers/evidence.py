"""
routers/evidence.py
===================
Endpoints for uploading usage evidence and tracking version increments.
"""

from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import AuthUser, require_reviewer
from app.models.case import Case
from app.schemas.evidence import (
    EvidenceUploadRequest,
    EvidenceUploadResponse,
    EvidenceRulesUploadRequest,
    EvidenceRulesUploadResponse,
)
from app.services.transition_service import (
    add_evidence_and_bump_version,
    add_rules_and_amendments_evidence,
)


router = APIRouter(prefix="/api/cases", tags=["evidence"])


@router.post("/{id}/evidence", response_model=EvidenceUploadResponse)
def upload_evidence(
    id: str,
    payload: EvidenceUploadRequest,
    user: Annotated[AuthUser, Depends(require_reviewer)],
    db: Session = Depends(get_db),
):
    """
    Uploads usage events for a case.
    Bumps evidence_version, marks existing findings stale, and transitions to REOPENED if arriving from RESOLVED.
    """
    case = db.query(Case).filter(Case.id == id).one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail=f"Case '{id}' not found")

    return add_evidence_and_bump_version(
        db=db,
        case=case,
        events_in=payload.events,
        actor=user.identity,
        source_note=payload.source_note,
    )


@router.post("/{id}/evidence/rules", response_model=EvidenceRulesUploadResponse)
def upload_rules_evidence(
    id: str,
    payload: EvidenceRulesUploadRequest,
    user: Annotated[AuthUser, Depends(require_reviewer)],
    db: Session = Depends(get_db),
):
    """
    Uploads contract rules, amendments, or adjustments for a case.
    Bumps evidence_version, supersedes existing rules if requested,
    marks findings/options stale, and transitions to REOPENED if arriving from RESOLVED.
    """
    case = db.query(Case).filter(Case.id == id).one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail=f"Case '{id}' not found")

    return add_rules_and_amendments_evidence(
        db=db,
        case=case,
        payload=payload,
        actor=user.identity,
    )

