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
from datetime import datetime, timezone
from typing import Optional
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.case import Case, CaseEvent, CaseStatus, VALID_TRANSITIONS
from app.models.investigation import Finding, ResolutionOption
from app.models.usage import UsageEvent, EvidenceVersion
from app.schemas.evidence import UsageEventIn, EvidenceUploadResponse


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
    old_status = case.status
    case.evidence_version += 1

    # Status becomes REOPENED only when arriving from RESOLVED
    if old_status == CaseStatus.RESOLVED.value:
        case.status = CaseStatus.REOPENED.value

    case.updated_at = datetime.now(timezone.utc)

    # Mark existing findings for this case as stale
    stale_count = (
        db.query(Finding)
        .filter(Finding.case_id == case.id, Finding.is_stale == False)  # noqa: E712
        .update({"is_stale": True})
    )

    # Mark existing resolution options as stale
    db.query(ResolutionOption).filter(
        ResolutionOption.case_id == case.id,
        ResolutionOption.is_stale == False,  # noqa: E712
    ).update({"is_stale": True})


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


    # Compute content hash of newly added events
    serialized_events = sorted(
        [{"id": e.event_id, "qty": str(e.quantity), "env": e.environment} for e in events_in],
        key=lambda x: x["id"],
    )
    content_hash = hashlib.sha256(json.dumps(serialized_events, sort_keys=True).encode()).hexdigest()

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

    db.commit()
    db.refresh(case)

    return EvidenceUploadResponse(
        case_id=case.id,
        new_evidence_version=case.evidence_version,
        events_uploaded=len(events_in),
        stale_findings_count=stale_count,
        case_status=case.status,
        content_hash=content_hash,
    )
