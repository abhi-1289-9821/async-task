"""
schemas/case.py
===============
Pydantic v2 schemas for Case creation, querying, and state transitions.
"""

from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.case import CaseStatus
from app.models.invoice import RuleTypeDB


class TierBandSchema(BaseModel):
    """
    Typed and validated tier band model.
    Enforces non-negative price and optional upper bound.
    """
    model_config = ConfigDict(extra="ignore")

    up_to: Optional[int] = Field(None, ge=1)
    price_per_unit_cents: Optional[int] = Field(None, ge=0)
    rate_cents: Optional[int] = Field(None, ge=0)

    @model_validator(mode="after")
    def validate_price(self) -> "TierBandSchema":
        if self.price_per_unit_cents is None and self.rate_cents is None:
            raise ValueError("Tier band requires 'price_per_unit_cents' or 'rate_cents'")
        if self.price_per_unit_cents is None:
            self.price_per_unit_cents = self.rate_cents
        elif self.rate_cents is None:
            self.rate_cents = self.price_per_unit_cents
        return self


class InvoiceLineCreate(BaseModel):
    id: str = Field(..., min_length=1, max_length=36)
    description: str = Field(..., min_length=1, max_length=255)
    original_amount_cents: int = Field(..., ge=0)


class ContractRuleCreate(BaseModel):
    id: str = Field(..., min_length=1, max_length=36)
    line_id: str = Field(..., min_length=1, max_length=36)
    rule_type: RuleTypeDB
    rate_cents: int = Field(0, ge=0)
    tiers: Optional[list[TierBandSchema]] = None
    discount_pct: Optional[float] = Field(None, ge=0.0, le=100.0, allow_inf_nan=False)
    minimum_commit_cents: int = Field(0, ge=0)
    included_units: int = Field(0, ge=0)
    overage_rate_cents: Optional[int] = Field(None, ge=0)
    exempt_environments: Optional[list[str]] = None
    supersedes_rule_id: Optional[str] = Field(None, max_length=36)

    @model_validator(mode="after")
    def validate_tiers_structure(self) -> "ContractRuleCreate":
        if self.rule_type == RuleTypeDB.DISCOUNT_PCT and self.discount_pct is None:
            raise ValueError("DISCOUNT_PCT rule requires 'discount_pct' to be specified")
        if self.tiers is not None:
            if not self.tiers:
                raise ValueError("Tiers list cannot be empty when provided")
            prev_bound = 0
            for i, t in enumerate(self.tiers):
                is_last = (i == len(self.tiers) - 1)
                if not is_last and t.up_to is None:
                    raise ValueError(f"Only the final tier can be unbounded (up_to=null), but tier {i} has up_to=null")
                if t.up_to is not None:
                    if t.up_to <= prev_bound:
                        raise ValueError(f"Tier bounds must be strictly ascending: tier {i} up_to ({t.up_to}) <= previous ({prev_bound})")
                    prev_bound = t.up_to
                if is_last and self.rule_type in (RuleTypeDB.TIERED_GRADUATED, RuleTypeDB.TIERED_VOLUME):
                    if t.up_to is not None:
                        raise ValueError("Final tier for tiered rules must be unbounded (up_to=null) to prevent uncovered usage")
        return self


class AdjustmentCreate(BaseModel):
    id: str = Field(..., min_length=1, max_length=36)
    invoice_line_id: Optional[str] = Field(None, min_length=1, max_length=36)
    amount_cents: int = Field(..., ge=0)
    description: str = Field(..., min_length=1)
    applied_at: Optional[datetime] = None
    is_verified: bool = True
    evidence_source: Optional[str] = Field(None, max_length=255)


class UsageEventCreate(BaseModel):
    id: Optional[str] = Field(None, max_length=64)
    line_id: str = Field(..., min_length=1, max_length=36)
    quantity: float = Field(..., ge=0)
    environment: str = Field(default="production", max_length=50)
    event_timestamp: Optional[datetime] = None


class CaseCreate(BaseModel):
    id: Optional[str] = Field(None, max_length=36)
    title: str = Field(..., min_length=3, max_length=255)
    customer_name: str = Field(..., min_length=1, max_length=100)
    invoice_id: Optional[str] = Field(None, max_length=64)
    currency: str = Field(default="USD", max_length=10)
    claimed_usage_quantity: Optional[float] = Field(None, ge=0)
    claimed_usage_uom: Optional[str] = Field(None, max_length=50)
    evidence_source: Optional[str] = Field(None, max_length=255)
    disputed_amount_cents: int = Field(..., ge=0)
    dispute_description: Optional[str] = Field(None, max_length=5000)
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    invoice_lines: list[InvoiceLineCreate] = Field(default_factory=list)
    contract_rules: list[ContractRuleCreate] = Field(default_factory=list)
    adjustments: list[AdjustmentCreate] = Field(default_factory=list)
    usage_events: list[UsageEventCreate] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_case_references(self) -> "CaseCreate":
        if self.period_start and self.period_end and self.period_start > self.period_end:
            raise ValueError("Billing period start date must be before or equal to end date")
        line_ids = {l.id for l in self.invoice_lines}
        for r in self.contract_rules:
            if r.line_id not in line_ids:
                raise ValueError(
                    f"Contract rule '{r.id}' references line_id '{r.line_id}' which does not exist in invoice_lines"
                )
        for adj in self.adjustments:
            if adj.invoice_line_id is not None and adj.invoice_line_id not in line_ids:
                raise ValueError(
                    f"Adjustment '{adj.id}' references invoice_line_id '{adj.invoice_line_id}' which does not exist in invoice_lines"
                )
        for ev in self.usage_events:
            if ev.line_id not in line_ids:
                raise ValueError(
                    f"Usage event '{ev.id or 'new'}' references line_id '{ev.line_id}' which does not exist in invoice_lines"
                )
        return self


class CaseTransitionRequest(BaseModel):
    target_status: CaseStatus
    note: Optional[str] = Field(None, max_length=500)


class CaseEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    case_id: str
    event_type: str
    actor: str
    details: Optional[dict[str, Any]] = None
    correlation_id: Optional[str] = None
    created_at: datetime


class InvoiceLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: str
    description: str
    original_amount_cents: int
    created_at: datetime


class ContractRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: str
    line_id: str
    rule_type: RuleTypeDB
    rate_cents: int
    tiers: Optional[list[TierBandSchema]] = None
    discount_pct: Optional[float] = None
    minimum_commit_cents: int
    included_units: int
    overage_rate_cents: Optional[int] = None
    exempt_environments: Optional[list[str]] = None
    is_active: bool = True
    supersedes_rule_id: Optional[str] = None
    created_at: datetime


class AdjustmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: str
    invoice_line_id: Optional[str] = None
    amount_cents: int
    description: str
    applied_at: Optional[datetime] = None
    is_verified: bool = True
    evidence_source: Optional[str] = None
    created_at: datetime


class CaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    customer_name: str
    invoice_id: Optional[str] = None
    currency: str = "USD"
    claimed_usage_quantity: Optional[float] = None
    claimed_usage_uom: Optional[str] = None
    disputed_amount_cents: int
    dispute_description: Optional[str] = None
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    status: CaseStatus
    evidence_version: int
    created_at: datetime
    updated_at: datetime
    invoice_lines: list[InvoiceLineResponse] = Field(default_factory=list)
    contract_rules: list[ContractRuleResponse] = Field(default_factory=list)
    adjustments: list[AdjustmentResponse] = Field(default_factory=list)
