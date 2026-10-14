"""
routers/cases.py
================
Endpoints for Case CRUD, status transitions, and audit events.
"""

import hashlib
import json
import uuid
from typing import Annotated, Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import AuthUser, get_current_user, require_reviewer
from app.models.case import Case, CaseEvent, CaseStatus
from app.models.invoice import InvoiceLine, ContractRule
from app.models.credit import Adjustment
from app.models.usage import UsageEvent, EvidenceVersion
from app.schemas.case import (
    CaseCreate,
    CaseResponse,
    CaseTransitionRequest,
    CaseEventResponse,
)
from app.services.transition_service import transition_case_status


router = APIRouter(prefix="/api/cases", tags=["cases"])


@router.post("", response_model=CaseResponse, status_code=status.HTTP_201_CREATED)
def create_case(
    payload: CaseCreate,
    user: Annotated[AuthUser, Depends(require_reviewer)],
    db: Session = Depends(get_db),
):
    """Creates a new billing dispute case with invoice lines and contract rules."""
    case_id = payload.id or f"case_{uuid.uuid4().hex[:12]}"
    existing = db.query(Case).filter(Case.id == case_id).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Case with ID '{case_id}' already exists")

    case = Case(
        id=case_id,
        title=payload.title,
        customer_name=payload.customer_name,
        invoice_id=payload.invoice_id,
        currency=payload.currency or "USD",
        claimed_usage_quantity=payload.claimed_usage_quantity,
        claimed_usage_uom=payload.claimed_usage_uom,
        disputed_amount_cents=payload.disputed_amount_cents,
        dispute_description=payload.dispute_description,
        period_start=payload.period_start,
        period_end=payload.period_end,
        status=CaseStatus.OPEN.value,
        evidence_version=1,
    )
    db.add(case)
    db.flush()

    # Add invoice lines
    created_lines = []
    for line in payload.invoice_lines:
        db_line = InvoiceLine(
            id=line.id,
            case_id=case_id,
            description=line.description,
            original_amount_cents=line.original_amount_cents,
        )
        db.add(db_line)
        created_lines.append(db_line)
    db.flush()

    # Add contract rules
    created_rules = []
    for rule in payload.contract_rules:
        tiers_data = [t.model_dump() for t in rule.tiers] if rule.tiers else None
        db_rule = ContractRule(
            id=rule.id,
            case_id=case_id,
            line_id=rule.line_id,
            rule_type=rule.rule_type,
            rate_cents=rule.rate_cents,
            tiers=tiers_data,
            discount_pct=rule.discount_pct,
            minimum_commit_cents=rule.minimum_commit_cents,
            included_units=rule.included_units,
            overage_rate_cents=rule.overage_rate_cents,
            exempt_environments=rule.exempt_environments,
        )
        db.add(db_rule)
        created_rules.append(db_rule)
    db.flush()

    # Add prior adjustments
    for adj in payload.adjustments:
        db_adj = Adjustment(
            id=adj.id,
            case_id=case_id,
            invoice_line_id=adj.invoice_line_id,
            amount_cents=adj.amount_cents,
            description=adj.description,
            applied_at=adj.applied_at,
            is_verified=adj.is_verified,
            evidence_source=adj.evidence_source,
        )
        db.add(db_adj)

    # Add initial usage events if provided
    created_events = []
    for ev in payload.usage_events:
        ev_id = ev.id or f"ev_{uuid.uuid4().hex[:12]}"
        db_ev = UsageEvent(
            id=ev_id,
            case_id=case_id,
            line_id=ev.line_id,
            quantity=ev.quantity,
            environment=ev.environment or "production",
            event_timestamp=ev.event_timestamp or payload.period_start,
        )
        db.add(db_ev)
        created_events.append(db_ev)
    db.flush()

    # Create initial EvidenceVersion snapshot (version 1)
    content_payload = json.dumps(
        {
            "lines": sorted([{"id": l.id, "original_amount_cents": l.original_amount_cents} for l in created_lines], key=lambda x: x["id"]),
            "rules": sorted([{"id": r.id, "rule_type": str(r.rule_type), "rate_cents": r.rate_cents} for r in created_rules], key=lambda x: x["id"]),
            "events": sorted([{"id": e.id, "quantity": float(e.quantity), "environment": e.environment} for e in created_events], key=lambda x: x["id"]),
        },
        sort_keys=True,
    )
    content_hash = hashlib.sha256(content_payload.encode()).hexdigest()
    ev_version = EvidenceVersion(
        case_id=case_id,
        version_number=1,
        content_hash=content_hash,
        created_by=user.identity,
    )
    db.add(ev_version)

    # Audit event
    event = CaseEvent(
        case_id=case_id,
        event_type="CASE_CREATED",
        actor=user.identity,
        details={
            "title": payload.title,
            "disputed_amount_cents": payload.disputed_amount_cents,
            "lines_count": len(payload.invoice_lines),
            "rules_count": len(payload.contract_rules),
            "events_count": len(payload.usage_events),
        },
    )
    db.add(event)

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Integrity conflict or duplicate primary key in dispute case creation",
        )
    db.refresh(case)
    return case


@router.get("", response_model=list[CaseResponse])
def list_cases(
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Lists all dispute cases."""
    return db.query(Case).order_by(Case.created_at.desc()).all()


@router.get("/{id}", response_model=CaseResponse)
def get_case(
    id: str,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Retrieves case details by ID."""
    case = db.query(Case).filter(Case.id == id).one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail=f"Case '{id}' not found")
    return case


@router.post("/{id}/transition", response_model=CaseResponse)
def transition_case(
    id: str,
    payload: CaseTransitionRequest,
    user: Annotated[AuthUser, Depends(require_reviewer)],
    db: Session = Depends(get_db),
):
    """
    Transitions case status.
    Returns HTTP 409 Conflict if the requested transition is invalid.
    """
    case = db.query(Case).filter(Case.id == id).one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail=f"Case '{id}' not found")

    return transition_case_status(
        db=db,
        case=case,
        target_status=payload.target_status,
        actor=user.identity,
        note=payload.note,
    )


@router.get("/{id}/events", response_model=list[CaseEventResponse])
def get_case_events(
    id: str,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Returns the immutable append-only audit trail for a case."""
    case = db.query(Case).filter(Case.id == id).one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail=f"Case '{id}' not found")

    return db.query(CaseEvent).filter(CaseEvent.case_id == id).order_by(CaseEvent.id.asc()).all()


@router.post("/reset-demo", response_model=dict[str, Any])
def reset_demo_cases_endpoint(
    user: Annotated[AuthUser, Depends(require_reviewer)],
    db: Session = Depends(get_db),
):
    """
    Explicit reset mechanism for genuine Acme demo scenarios.
    Resets Scenario A (missing telemetry) and Scenario B (verified tier overcharge).
    """
    from app.seed import seed_demo_cases
    seeded_ids = seed_demo_cases(db, force=True)
    return {"status": "ok", "message": "Demo cases successfully reset", "cases": seeded_ids}
