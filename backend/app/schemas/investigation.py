"""
schemas/investigation.py
========================
Pydantic v2 schemas for investigation runs, findings, resolution options, and human reviews.
"""

from datetime import datetime
from typing import Any, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class FindingReviewRequest(BaseModel):
    action: Literal["ACCEPT", "EDIT", "REJECT"]
    note: Optional[str] = Field(None, max_length=1000)
    edited_text: Optional[str] = Field(None, max_length=5000)


class FindingReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    finding_id: str
    reviewer: str
    action: str
    note: Optional[str] = None
    original_ai_text: Optional[str] = None
    edited_text: Optional[str] = None
    reviewed_at: datetime


class ResolutionOptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    case_id: str
    option_type: str
    description: str
    calculation_line_result_id: Optional[int] = None
    is_stale: bool
    stale_reason: Optional[str] = None
    created_at: datetime


class FindingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: str
    run_id: str
    finding_type: str
    raw_ai_text: Optional[str] = None
    calculation_line_result_id: Optional[int] = None
    verified_facts: Optional[list[Any]] = None
    possible_explanations: Optional[list[Any]] = None
    assumptions: Optional[list[Any]] = None
    open_questions: Optional[list[Any]] = None
    missing_evidence_questions: Optional[list[Any]] = None
    citation_ids: Optional[list[str]] = None
    citation_validation_passed: bool = False
    consistency_check_passed: bool = False
    is_stale: bool = False
    stale_reason: Optional[str] = None
    created_at: datetime
    reviews: list[FindingReviewResponse] = Field(default_factory=list)


class InvestigationRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: str
    calculation_id: Optional[str] = None
    evidence_version: int
    status: str
    status_reason: Optional[str] = None
    token_usage: Optional[dict[str, Any]] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    findings: list[FindingResponse] = Field(default_factory=list)
    resolution_options: list[ResolutionOptionResponse] = Field(default_factory=list)
