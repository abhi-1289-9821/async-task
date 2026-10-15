"""
routers/investigations.py
=========================
FastAPI endpoints to trigger and inspect LangGraph investigation runs.
"""

from datetime import datetime, timedelta, timezone
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent.graph import run_investigation
from app.agent.providers import has_configured_provider
from app.config import settings
from app.database import get_db
from app.middleware.auth import AuthUser, get_current_user, require_reviewer
from app.models.case import Case, CaseEvent
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

    if not has_configured_provider():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No LLM provider configured. Please configure an API key for Gemini, Groq, or OpenRouter.",
        )

    # Repeat-run guard: check for existing RUNNING runs.
    # Treat runs older than INVESTIGATION_RUN_TTL_SECONDS as abandoned.
    active_runs = (
        db.query(InvestigationRun)
        .filter(
            InvestigationRun.case_id == case_id,
            InvestigationRun.status == RunStatus.RUNNING,
        )
        .all()
    )

    ttl_seconds = settings.investigation_run_ttl_seconds
    now_utc = datetime.now(timezone.utc)

    for active_run in active_runs:
        started = active_run.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        age_seconds = (now_utc - started).total_seconds()

        if age_seconds > ttl_seconds:
            # Reaped abandoned run
            active_run.status = RunStatus.FAILED
            active_run.status_reason = "Abandoned: exceeded TTL"
            active_run.completed_at = now_utc
            failed_event = CaseEvent(
                case_id=case_id,
                event_type="INVESTIGATION_RUN_FAILED",
                actor="SYSTEM",
                details={
                    "run_id": active_run.id,
                    "reason": "Abandoned: exceeded TTL",
                    "exceeded_ttl_seconds": ttl_seconds,
                },
            )
            db.add(failed_event)
            db.commit()
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"An investigation run ({active_run.id}) is already currently running for case '{case_id}'",
            )

    try:
        db_run = run_investigation(
            db=db,
            case_id=case_id,
            actor=user.identity,
        )
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An investigation run is already currently running for case '{case_id}'",
        )
    except Exception as exc:
        db.rollback()
        # Ensure run never remains in RUNNING when an exception occurs
        try:
            stuck_runs = db.query(InvestigationRun).filter(
                InvestigationRun.case_id == case_id,
                InvestigationRun.status == RunStatus.RUNNING,
            ).all()
            for sr in stuck_runs:
                sr.status = RunStatus.FAILED
                sr.status_reason = f"Investigation failed: {exc}"
                sr.completed_at = datetime.now(timezone.utc)
            db.commit()
        except Exception:
            db.rollback()
        raise
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
