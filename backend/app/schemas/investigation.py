"""
schemas/investigation.py
========================
Pydantic v2 schemas for findings, resolution options, and human reviews.
"""

from datetime import datetime
from typing import Literal, Optional
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
    original_ai_text: str
    edited_text: Optional[str] = None
    reviewed_at: datetime


class ResolutionOptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    finding_id: str
    option_type: str
    calculation_line_result_id: Optional[int] = None
    recommended_credit_cents: int
    narrative: str
    is_stale: bool
    created_at: datetime


class FindingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: str
    run_id: str
    calculation_line_result_id: Optional[int] = None
    finding_type: str
    raw_ai_text: str
    is_stale: bool
    created_at: datetime
    reviews: list[FindingReviewResponse] = Field(default_factory=list)
    resolution_options: list[ResolutionOptionResponse] = Field(default_factory=list)
