"""
schemas/credit.py
=================
Pydantic v2 schemas for credit approval, authoritative cap ledger, and tracking.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class CreditCapResponse(BaseModel):
    """Authoritative cap breakdown and credit governance metrics for an invoice line."""
    model_config = ConfigDict(extra="ignore")

    # Authoritative ledger metrics
    original: Optional[int] = None
    original_billed_cents: Optional[int] = None
    recalculated: Optional[int] = None
    recalculated_cents: Optional[int] = None
    gross_discrepancy: Optional[int] = None
    gross_discrepancy_cents: Optional[int] = None
    verified_adjustments: int = 0
    line_adjustments_cents: int = 0
    case_wide_adjustments_cents: int = 0
    unverified_adjustments: int = 0
    unverified_adjustments_cents: int = 0
    prior_credits: int = 0
    prior_credits_cents: int = 0
    eligible_overcharge: int = 0
    eligible_cents: int = 0
    remaining_cap: int = 0
    remaining_cap_cents: int = 0
    issued_credit_cents: int = 0
    approval_eligibility: str = "BLOCKED"  # "ELIGIBLE" | "PENDING_REVIEW" | "BLOCKED"
    is_eligible: bool = False
    reason: Optional[str] = None
    blocked_reason: Optional[str] = None
    currency: str = "USD"


class CreditApproveRequest(BaseModel):
    case_id: str = Field(..., min_length=1, max_length=36)
    invoice_line_id: str = Field(..., min_length=1, max_length=36)
    reason_code: str = Field(..., min_length=1, max_length=50)
    finding_id: str = Field(..., min_length=1, max_length=36)
    resolution_option_id: Optional[str] = Field(None, max_length=36)
    reason_note: Optional[str] = Field(None, max_length=1000)
    requested_amount_cents: Optional[int] = Field(None, gt=0, le=10**9)
    idempotency_key: Optional[str] = Field(None, max_length=64)


class CreditResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: str
    invoice_line_id: str
    finding_id: Optional[str] = None
    resolution_option_id: Optional[str] = None
    calculation_line_result_id: Optional[int] = None
    idempotency_key: str
    amount_cents: int
    reason_code: str
    reason_note: Optional[str] = None
    approved_by: str
    approved_at: datetime
    created_at: datetime
