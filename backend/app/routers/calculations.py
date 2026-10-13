"""
routers/calculations.py
======================
Endpoints for executing the deterministic calculation engine and viewing results.
"""

from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import AuthUser, get_current_user, require_reviewer
from app.models.calculation import Calculation
from app.schemas.calculation import CalculationRunRequest, CalculationResponse
from app.services.calculation_service import execute_case_calculation


router = APIRouter(prefix="/api/calculations", tags=["calculations"])


@router.post("/run", response_model=CalculationResponse, status_code=status.HTTP_201_CREATED)
def run_calculation(
    payload: CalculationRunRequest,
    user: Annotated[AuthUser, Depends(require_reviewer)],
    db: Session = Depends(get_db),
):
    """
    Executes the pure deterministic billing engine on the latest case evidence.
    Persists immutable calculation results and line items.
    """
    return execute_case_calculation(
        db=db,
        case_id=payload.case_id,
        actor=user.identity,
    )


@router.get("/{id}", response_model=CalculationResponse)
def get_calculation(
    id: str,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Retrieves calculation result and line items by calculation ID."""
    calc = db.query(Calculation).filter(Calculation.id == id).one_or_none()
    if not calc:
        raise HTTPException(status_code=404, detail=f"Calculation '{id}' not found")
    return calc


@router.get("/case/{case_id}", response_model=list[CalculationResponse])
def get_case_calculations(
    case_id: str,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Retrieves all calculations run for a given case."""
    return db.query(Calculation).filter(Calculation.case_id == case_id).order_by(Calculation.created_at.desc()).all()
