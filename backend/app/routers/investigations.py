"""
routers/investigations.py
=========================
FastAPI endpoints to trigger and inspect LangGraph investigation runs.
"""

from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.agent.graph import run_investigation
from app.database import get_db
from app.middleware.auth import AuthUser, get_current_user, require_reviewer
from app.models.case import Case
from app.models.investigation import InvestigationRun, RunStatus
from app.schemas.investigation import InvestigationRunResponse

router = APIRouter(tags=["investigations"])


@router.post(
    "/api/cases/{case_id}/investigations",
    response_model=InvestigationRunResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_502_BAD_GATEWAY: {
            "description": "Investigation run failed due to upstream provider failures"
        }
    },
)
def trigger_investigation(
    case_id: str,
    response: Response,
    user: Annotated[AuthUser, Depends(require_reviewer)],
    db: Session = Depends(get_db),
):
    """
    Triggers an autonomous LangGraph investigation run for a case.
    - Gathers evidence and checks completeness.
    - Executes deterministic billing engine.
    - Generates structured findings with deterministic citations.
    - Formulates verified resolution options.
    """
    case = db.query(Case).filter(Case.id == case_id).one_or_none()
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case '{case_id}' not found",
        )

    # Repeat-run guard: reject concurrent investigation runs for the same case
    active_run = (
        db.query(InvestigationRun)
        .filter(
            InvestigationRun.case_id == case_id,
            InvestigationRun.status == RunStatus.RUNNING,
        )
        .first()
    )
    if active_run:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An investigation run ({active_run.id}) is already currently running for case '{case_id}'",
        )

    db_run = run_investigation(
        db=db,
        case_id=case_id,
        actor=user.identity,
    )
    if db_run.status == RunStatus.FAILED:
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={
                "id": db_run.id,
                "run_id": db_run.id,
                "status": "FAILED",
                "reason": db_run.status_reason,
                "status_reason": db_run.status_reason,
            },
        )
    return db_run


@router.get(
    "/api/cases/{case_id}/investigations",
    response_model=list[InvestigationRunResponse],
)
def list_case_investigations(
    case_id: str,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Lists all investigation runs for a case."""
    case = db.query(Case).filter(Case.id == case_id).one_or_none()
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case '{case_id}' not found",
        )

    return (
        db.query(InvestigationRun)
        .filter(InvestigationRun.case_id == case_id)
        .order_by(InvestigationRun.started_at.desc())
        .all()
    )


@router.get(
    "/api/investigations/{id}",
    response_model=InvestigationRunResponse,
)
def get_investigation_run(
    id: str,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Retrieves full details of a specific investigation run."""
    run = db.query(InvestigationRun).filter(InvestigationRun.id == id).one_or_none()
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Investigation run '{id}' not found",
        )
    return run
