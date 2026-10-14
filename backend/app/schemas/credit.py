"""
schemas/credit.py
=================
Pydantic v2 schemas for credit approval and tracking.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class CreditCapResponse(BaseModel):
    """Read-only cap breakdown for a given invoice line. Returned by GET /api/credits/case/{id}/cap."""
    eligible_cents: int
    prior_credits_cents: int
    line_adjustments_cents: int
    case_wide_adjustments_cents: int
    remaining_cap_cents: int


class CreditApproveRequest(BaseModel):
    case_id: str = Field(..., min_length=1, max_length=36)
    invoice_line_id: str = Field(..., min_length=1, max_length=36)
    reason_code: str = Field(..., min_length=1, max_length=50)
    finding_id: str = Field(..., min_length=1, max_length=36)
    resolution_option_id: Optional[str] = Field(None, max_length=36)
    reason_note: Optional[str] = Field(None, max_length=1000)
    requested_amount_cents: Optional[int] = Field(None, gt=0)
    idempotency_key: Optional[str] = Field(None, max_length=64)


class CreditResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: str
    invoice_line_id: str
    resolution_option_id: Optional[str] = None
    calculation_line_result_id: Optional[int] = None
    idempotency_key: str
    amount_cents: int
    reason_code: str
    reason_note: Optional[str] = None
    approved_by: str
    approved_at: datetime
    created_at: datetime

