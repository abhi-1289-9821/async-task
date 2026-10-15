"""
services/transition_service.py
==============================
State machine transition enforcement and evidence version bumping.

State Machine Rules:
  - Valid transitions:
      OPEN          -> AWAITING_INFO, RESOLVED
      AWAITING_INFO -> OPEN, RESOLVED
      RESOLVED      -> REOPENED (only RESOLVED can transition to REOPENED)
      REOPENED      -> OPEN, AWAITING_INFO, RESOLVED
  - Invalid transitions raise HTTP 409 Conflict.
  - Adding evidence in ANY status:
      - Bumps case.evidence_version by 1
      - Marks all existing findings and resolution options for the case as is_stale = True
      - Transitions status to REOPENED if and only if the current status is RESOLVED
      - Creates append-only audit events in case_events
"""

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Optional
from fastapi import HTTPException, status
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from app.models.case import Case, CaseEvent, CaseStatus, VALID_TRANSITIONS
from app.models.credit import Adjustment
from app.models.investigation import Finding, ResolutionOption
from app.models.invoice import ContractRule, InvoiceLine, RuleTypeDB
from app.models.usage import UsageEvent, EvidenceVersion
from app.schemas.evidence import (
    UsageEventIn,
    EvidenceUploadResponse,
    EvidenceRulesUploadRequest,
    EvidenceRulesUploadResponse,
)


def transition_case_status(
    db: Session,
    case: Case,
    target_status: CaseStatus,
    actor: str,
    note: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> Case:
    """
    Executes a status transition for a case.
    Raises HTTP 409 Conflict if the transition is not in VALID_TRANSITIONS.
    Appends an immutable audit event to case_events.
    """
    current_status = case.status
    transition_tuple = (current_status, target_status.value)

    if transition_tuple not in VALID_TRANSITIONS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Invalid case status transition from '{current_status}' to '{target_status.value}'. "
                f"Permitted transitions from '{current_status}': "
                f"{[to for (frm, to) in VALID_TRANSITIONS if frm == current_status]}"
            ),
        )

    case.status = target_status.value
    case.updated_at = datetime.now(timezone.utc)

    # Append-only audit event
    event = CaseEvent(
        case_id=case.id,
        event_type="STATUS_CHANGED",
        actor=actor,
        details={
            "from_status": current_status,
            "to_status": target_status.value,
            "note": note,
        },
        correlation_id=correlation_id,
    )
    db.add(event)
    db.commit()
    db.refresh(case)
    return case


def compute_case_content_hash(db: Session, case: Case) -> str:
    """
    Computes a deterministic SHA-256 content hash across all lines, contract rules,
    adjustments, and usage events for the case.
    Includes discount_pct, minimum_commit_cents, included_units, overage_rate_cents,
    exempt_environments, event timestamps, is_active, and supersedes_rule_id.
    """
    events = db.query(UsageEvent).filter(UsageEvent.case_id == case.id).all()
    serialized_events = sorted(
        [
            {
                "id": e.id,
                "line_id": e.line_id,
                "qty": str(e.quantity),
                "env": e.environment,
                "timestamp": e.event_timestamp.isoformat() if e.event_timestamp else None,
            }
            for e in events
        ],
        key=lambda x: x["id"],
    )

    lines = db.query(InvoiceLine).filter(InvoiceLine.case_id == case.id).all()
    serialized_lines = sorted(
        [{"id": l.id, "desc": l.description, "amt": l.original_amount_cents} for l in lines],
        key=lambda x: x["id"],
    )

    rules = db.query(ContractRule).filter(ContractRule.case_id == case.id).all()
    serialized_rules = sorted(
        [
            {
                "id": r.id,
                "line_id": r.line_id,
                "type": str(r.rule_type.value if hasattr(r.rule_type, "value") else r.rule_type),
                "rate": r.rate_cents,
                "tiers": r.tiers,
                "discount_pct": str(r.discount_pct) if r.discount_pct is not None else None,
                "minimum_commit_cents": r.minimum_commit_cents,
                "included_units": r.included_units,
                "overage_rate_cents": r.overage_rate_cents,
                "exempt_environments": r.exempt_environments,
                "is_active": r.is_active,
                "supersedes_rule_id": r.supersedes_rule_id,
            }
            for r in rules
        ],
        key=lambda x: x["id"],
    )

    adjustments = db.query(Adjustment).filter(Adjustment.case_id == case.id).all()
    serialized_adjustments = sorted(
        [
            {
                "id": a.id,
                "line_id": a.invoice_line_id,
                "amount": a.amount_cents,
                "desc": a.description,
            }
            for a in adjustments
        ],
        key=lambda x: x["id"],
    )

    payload = {
        "lines": serialized_lines,
        "rules": serialized_rules,
        "adjustments": serialized_adjustments,
        "events": serialized_events,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def add_evidence_and_bump_version(
    db: Session,
    case: Case,
    events_in: list[UsageEventIn],
    actor: str,
    source_note: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> EvidenceUploadResponse:
    """
    Adds new usage events for a case, increments the evidence version,
    marks existing findings as stale, and transitions to REOPENED if arriving from RESOLVED.
    """
    # 1. Validate line_id against case invoice lines
    valid_line_ids = {l.id for l in db.query(InvoiceLine).filter(InvoiceLine.case_id == case.id).all()}
    for ev in events_in:
        if ev.line_id not in valid_line_ids:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Usage event '{ev.event_id}' line_id '{ev.line_id}' is not associated with case '{case.id}'",
            )

    # 2. Check for duplicate event IDs within incoming payload (Task 9b)
    seen_ids = set()
    payload_duplicates = []
    for ev in events_in:
        if ev.event_id in seen_ids:
            payload_duplicates.append(ev.event_id)
        seen_ids.add(ev.event_id)
    if payload_duplicates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Duplicate event IDs detected in payload: {', '.join(sorted(payload_duplicates))}",
        )

    # 3. Check for duplicates against existing events in DB (Task 9b)
    existing_events = (
        db.query(UsageEvent.id)
        .filter(UsageEvent.case_id == case.id, UsageEvent.id.in_([ev.event_id for ev in events_in]))
        .all()
    )
    if existing_events:
        dup_ids = [row[0] for row in existing_events]
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Duplicate event IDs already exist in case '{case.id}': {', '.join(sorted(dup_ids))}",
        )

    # 4. Acquire lock on case row to prevent race conditions during version bump
    try:
        locked_case = db.query(Case).filter(Case.id == case.id).with_for_update().first()
        if locked_case:
            case = locked_case
    except (OperationalError, SQLAlchemyError) as exc:
        logger.debug("Row locking not supported or skipped: %s", exc)

    old_status = case.status
    case.evidence_version += 1

    # Status becomes REOPENED only when arriving from RESOLVED
    if old_status == CaseStatus.RESOLVED.value:
        case.status = CaseStatus.REOPENED.value

    case.updated_at = datetime.now(timezone.utc)

    # Mark existing findings for this case as stale with explicit reason
    stale_reason_text = (
        f"New evidence uploaded (evidence version bumped from {case.evidence_version - 1} to {case.evidence_version}). "
        "Investigation rerun required."
    )
    stale_count = (
        db.query(Finding)
        .filter(Finding.case_id == case.id, Finding.is_stale == False)  # noqa: E712
        .update({
            "is_stale": True,
            "stale_reason": stale_reason_text,
        })
    )

    # Mark existing resolution options as stale WITH stale_reason
    db.query(ResolutionOption).filter(
        ResolutionOption.case_id == case.id,
        ResolutionOption.is_stale == False,  # noqa: E712
    ).update({
        "is_stale": True,
        "stale_reason": stale_reason_text,
    })

    # Insert usage event rows
    new_db_events: list[UsageEvent] = []
    for ev in events_in:
        db_ev = UsageEvent(
            id=ev.event_id,
            case_id=case.id,
            line_id=ev.line_id,
            event_timestamp=ev.timestamp,
            quantity=ev.quantity,
            environment=ev.environment,
        )
        new_db_events.append(db_ev)
    db.add_all(new_db_events)
    db.flush()

    # Compute content hash of all inputs (lines, rules, adjustments, and events) for this case
    content_hash = compute_case_content_hash(db, case)

    # Record EvidenceVersion snapshot
    evidence_ver_record = EvidenceVersion(
        case_id=case.id,
        version_number=case.evidence_version,
        content_hash=content_hash,
        created_by=actor,
    )
    db.add(evidence_ver_record)

    # Append-only audit event
    audit_event = CaseEvent(
        case_id=case.id,
        event_type="EVIDENCE_UPLOADED",
        actor=actor,
        details={
            "evidence_version": case.evidence_version,
            "events_added": len(events_in),
            "stale_findings_marked": stale_count,
            "source_note": source_note,
            "previous_status": old_status,
            "current_status": case.status,
        },
        correlation_id=correlation_id,
    )
    db.add(audit_event)

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.exception("Database conflict during evidence upload: %s", e)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Database conflict occurred while saving evidence. Check for conflicting records.",
        )
    db.refresh(case)

    return EvidenceUploadResponse(
        case_id=case.id,
        new_evidence_version=case.evidence_version,
        events_uploaded=len(events_in),
        stale_findings_count=stale_count,
        case_status=case.status,
        content_hash=content_hash,
    )


def add_rules_and_amendments_evidence(
    db: Session,
    case: Case,
    payload: EvidenceRulesUploadRequest,
    actor: str,
    correlation_id: Optional[str] = None,
) -> EvidenceRulesUploadResponse:
    """
    Uploads contract rules, adjustments, or updated dispute descriptions as new evidence.
    Bumps evidence_version, supersedes existing rules if requested, marks existing findings
    and resolution options stale with stale_reason, and reopens RESOLVED cases to REOPENED.
    """
    valid_line_ids = {l.id for l in db.query(InvoiceLine).filter(InvoiceLine.case_id == case.id).all()}

    # Validate line ids on contract rules
    for r in (payload.contract_rules or []):
        if r.line_id not in valid_line_ids:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Contract rule '{r.id}' line_id '{r.line_id}' is not associated with case '{case.id}'",
            )
    # Validate line ids on adjustments
    for a in (payload.adjustments or []):
        if a.invoice_line_id and a.invoice_line_id not in valid_line_ids:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Adjustment '{a.id}' invoice_line_id '{a.invoice_line_id}' is not associated with case '{case.id}'",
            )

    # Check for duplicate rule ids within payload
    rule_ids = [r.id for r in (payload.contract_rules or [])]
    if len(rule_ids) != len(set(rule_ids)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Duplicate contract rule IDs detected in payload",
        )
    if rule_ids:
        existing_rules = {
            row[0]
            for row in db.query(ContractRule.id)
            .filter(ContractRule.case_id == case.id, ContractRule.id.in_(rule_ids))
            .all()
        }
        if existing_rules:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Contract rule IDs already exist in case '{case.id}': {', '.join(sorted(existing_rules))}",
            )

    # Acquire lock on case
    try:
        locked_case = db.query(Case).filter(Case.id == case.id).with_for_update().first()
        if locked_case:
            case = locked_case
    except (OperationalError, SQLAlchemyError) as exc:
        logger.debug("Row locking not supported or skipped: %s", exc)

    # Validate supersedes_rule_id before mutating case state
    for r in (payload.contract_rules or []):
        if r.supersedes_rule_id:
            existing_target = (
                db.query(ContractRule)
                .filter(ContractRule.case_id == case.id, ContractRule.id == r.supersedes_rule_id)
                .first()
            )
            if not existing_target:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"supersedes_rule_id '{r.supersedes_rule_id}' is not an existing rule on case '{case.id}'",
                )

    old_status = case.status
    case.evidence_version += 1

    if old_status == CaseStatus.RESOLVED.value:
        case.status = CaseStatus.REOPENED.value

    if payload.dispute_description is not None:
        case.dispute_description = payload.dispute_description

    case.updated_at = datetime.now(timezone.utc)

    # Mark findings and options stale with reason
    stale_reason_text = (
        f"Contract rules or adjustments evidence updated (evidence version bumped from {case.evidence_version - 1} to {case.evidence_version}). "
        "Investigation rerun required."
    )
    stale_count = (
        db.query(Finding)
        .filter(Finding.case_id == case.id, Finding.is_stale == False)  # noqa: E712
        .update({"is_stale": True, "stale_reason": stale_reason_text})
    )
    db.query(ResolutionOption).filter(
        ResolutionOption.case_id == case.id,
        ResolutionOption.is_stale == False,  # noqa: E712
    ).update({"is_stale": True, "stale_reason": stale_reason_text})

    # Supersede existing rules and insert new contract rules
    new_db_rules = []
    for r in (payload.contract_rules or []):
        if r.supersedes_rule_id:
            old_r = (
                db.query(ContractRule)
                .filter(ContractRule.case_id == case.id, ContractRule.id == r.supersedes_rule_id)
                .first()
            )
            if old_r:
                old_r.is_active = False

            # If replacing on the same line with a primary rule of the same type, deactivate prior rules of that type
            if r.rule_type in (RuleTypeDB.TIERED_GRADUATED, RuleTypeDB.TIERED_VOLUME, RuleTypeDB.PER_UNIT, RuleTypeDB.FLAT):
                prior_same = (
                    db.query(ContractRule)
                    .filter(
                        ContractRule.case_id == case.id,
                        ContractRule.line_id == r.line_id,
                        ContractRule.rule_type == r.rule_type,
                        ContractRule.id != r.id,
                    )
                    .all()
                )
                for pr in prior_same:
                    pr.is_active = False

        tiers_json = [t.model_dump() for t in r.tiers] if r.tiers else None
        db_rule = ContractRule(
            id=r.id,
            case_id=case.id,
            line_id=r.line_id,
            rule_type=r.rule_type,
            rate_cents=r.rate_cents,
            tiers=tiers_json,
            discount_pct=r.discount_pct,
            minimum_commit_cents=r.minimum_commit_cents,
            included_units=r.included_units,
            overage_rate_cents=r.overage_rate_cents,
            exempt_environments=r.exempt_environments,
            is_active=True,
            supersedes_rule_id=r.supersedes_rule_id,
        )
        new_db_rules.append(db_rule)
    db.add_all(new_db_rules)

    # Insert adjustments
    new_db_adjustments = []
    for a in (payload.adjustments or []):
        db_adj = Adjustment(
            id=a.id,
            case_id=case.id,
            invoice_line_id=a.invoice_line_id,
            amount_cents=a.amount_cents,
            description=a.description,
            applied_at=a.applied_at or datetime.now(timezone.utc),
        )
        new_db_adjustments.append(db_adj)
    db.add_all(new_db_adjustments)

    db.flush()

    # Recompute content hash across all inputs
    content_hash = compute_case_content_hash(db, case)

    # Create EvidenceVersion snapshot
    evidence_ver_record = EvidenceVersion(
        case_id=case.id,
        version_number=case.evidence_version,
        content_hash=content_hash,
        created_by=actor,
    )
    db.add(evidence_ver_record)

    # Append-only audit event
    audit_event = CaseEvent(
        case_id=case.id,
        event_type="EVIDENCE_UPLOADED",
        actor=actor,
        details={
            "evidence_version": case.evidence_version,
            "rules_added": len(new_db_rules),
            "adjustments_added": len(new_db_adjustments),
            "stale_findings_marked": stale_count,
            "source_note": payload.source_note,
            "previous_status": old_status,
            "current_status": case.status,
            "evidence_type": "CONTRACT_RULES_AND_AMENDMENTS",
        },
        correlation_id=correlation_id,
    )
    db.add(audit_event)

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.exception("Database conflict during rule evidence upload: %s", e)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Database conflict occurred while saving rule evidence.",
        )
    db.refresh(case)

    return EvidenceRulesUploadResponse(
        case_id=case.id,
        new_evidence_version=case.evidence_version,
        rules_uploaded=len(new_db_rules),
        adjustments_uploaded=len(new_db_adjustments),
        stale_findings_count=stale_count,
        case_status=case.status,
        content_hash=content_hash,
    )

