"""
models/__init__.py
==================
Import all models so SQLAlchemy's Base.metadata sees them
before create_all() or Alembic inspects the metadata.
"""

from app.models.case import Case, CaseEvent, CaseStatus, VALID_TRANSITIONS
from app.models.invoice import InvoiceLine, ContractRule, RuleTypeDB
from app.models.usage import UsageEvent, EvidenceVersion
from app.models.calculation import Calculation, CalculationLineResult, EngineStatusDB, FindingTypeDB
from app.models.investigation import (
    InvestigationRun, Finding, FindingReview, ResolutionOption,
    RunStatus, AgentFindingType, OptionType, ReviewDecision,
)
from app.models.credit import Credit, Adjustment

__all__ = [
    "Case", "CaseEvent", "CaseStatus", "VALID_TRANSITIONS",
    "InvoiceLine", "ContractRule", "RuleTypeDB",
    "UsageEvent", "EvidenceVersion",
    "Calculation", "CalculationLineResult", "EngineStatusDB", "FindingTypeDB",
    "InvestigationRun", "Finding", "FindingReview", "ResolutionOption",
    "RunStatus", "AgentFindingType", "OptionType", "ReviewDecision",
    "Credit", "Adjustment",
]
