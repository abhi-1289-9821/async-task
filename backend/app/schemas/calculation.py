"""
schemas/calculation.py
======================
Pydantic v2 schemas for billing engine runs and results.
"""

from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field

from app.models.calculation import EngineStatusDB, FindingTypeDB


class CalculationRunRequest(BaseModel):
    case_id: str = Field(..., min_length=1, max_length=36)


class CalculationLineResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    calculation_id: str
    line_id: str
    result_id: str
    rule_id: str
    original_amount_cents: int
    recalculated_amount_cents: int
    difference_cents: int
    finding_type: FindingTypeDB
    quantity_used: float
    exempt_quantity: float
    applied_discount_pct: Optional[float] = None
    applied_minimum_commit_cents: int = 0
    interpretations: Optional[list[dict[str, Any]]] = None
    assumptions: Optional[list[str]] = None
    explanation: str
    quarantined_events: Optional[list[dict[str, Any]]] = None


class CalculationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: str
    evidence_version: int
    engine_status: EngineStatusDB
    engine_status_reason: Optional[str] = None
    total_original_billed_cents: int
    total_recalculated_cents: int
    total_difference_cents: int
    result_hash: str
    created_at: datetime
    line_results: list[CalculationLineResultResponse] = Field(default_factory=list)
