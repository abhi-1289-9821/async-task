"""
services/calculation_service.py
===============================
Orchestrates loading case data from the database, invoking the deterministic
billing engine, and persisting the immutable calculation results.
"""

import uuid
from decimal import Decimal
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app import billing_engine as engine
from app.models.case import Case, CaseEvent
from app.models.invoice import InvoiceLine as DBInvoiceLine, ContractRule as DBContractRule
from app.models.usage import UsageEvent as DBUsageEvent
from app.models.calculation import Calculation, CalculationLineResult, EngineStatusDB, FindingTypeDB


def execute_case_calculation(
    db: Session,
    case_id: str,
    actor: str,
    correlation_id: str | None = None,
) -> Calculation:
    """
    Executes the deterministic billing engine for a case, saves calculation results,
    and returns the persisted Calculation model.
    """
    case = db.query(Case).filter(Case.id == case_id).one_or_none()
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case '{case_id}' not found",
        )

    # Load invoice lines
    db_lines = db.query(DBInvoiceLine).filter(DBInvoiceLine.case_id == case_id).all()
    if not db_lines:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Case '{case_id}' has no invoice lines",
        )

    # Load contract rules (active only)
    db_rules = (
        db.query(DBContractRule)
        .filter(DBContractRule.case_id == case_id, DBContractRule.is_active == True)
        .all()
    )

    # Load usage events
    db_events = db.query(DBUsageEvent).filter(DBUsageEvent.case_id == case_id).all()

    # Convert to pure engine dataclasses
    engine_lines = [
        engine.InvoiceLine(
            line_id=l.id,
            description=l.description,
            original_amount_cents=l.original_amount_cents,
        )
        for l in db_lines
    ]

    engine_rules: list[engine.ContractRule] = []
    for r in db_rules:
        # Convert JSON tiers if present
        tiers = None
        if r.tiers:
            tiers = []
            for t in r.tiers:
                price = t.get("price_per_unit_cents")
                if price is None:
                    price = t.get("rate_cents")
                if price is None:
                    raise ValueError(f"Tier definition missing price_per_unit_cents or rate_cents: {t}")
                tiers.append(engine.TierBand(
                    price_per_unit_cents=price,
                    up_to=t.get("up_to"),
                ))


        engine_rules.append(
            engine.ContractRule(
                rule_id=r.id,
                line_id=r.line_id,
                rule_type=engine.RuleType(r.rule_type.value),
                rate_cents=r.rate_cents,
                tiers=tiers,
                discount_pct=Decimal(str(r.discount_pct)) if r.discount_pct is not None else None,
                minimum_commit_cents=r.minimum_commit_cents,
                included_units=Decimal(str(r.included_units)),
                overage_rate_cents=r.overage_rate_cents,
                exempt_environments=r.exempt_environments or [],
            )
        )

    engine_events = [
        engine.UsageEvent(
            event_id=e.id,
            line_id=e.line_id,
            quantity=Decimal(str(e.quantity)),
            environment=e.environment,
            timestamp=e.event_timestamp,
            raw={},
        )
        for e in db_events
    ]

    # Run pure calculation engine
    engine_result = engine.run_calculation(
        engine_lines,
        engine_rules,
        engine_events,
        period_start=case.period_start,
        period_end=case.period_end,
    )

    # Persist Calculation record
    calc_id = f"calc_{uuid.uuid4().hex[:12]}"
    all_quarantined_data = [
        {
            "event_id": q.event_id,
            "reason": q.reason,
            "raw": q.raw,
        }
        for q in engine_result.quarantined_events
    ] if engine_result.quarantined_events else None

    db_calc = Calculation(
        id=calc_id,
        case_id=case.id,
        evidence_version=case.evidence_version,
        engine_status=EngineStatusDB(engine_result.status.value),
        engine_status_reason=engine_result.status_reason,
        total_original_billed_cents=engine_result.total_original_billed_cents,
        total_recalculated_cents=engine_result.total_recalculated_cents,
        total_difference_cents=engine_result.total_difference_cents,
        result_hash=engine_result.result_hash,
        quarantined_events=all_quarantined_data,
    )
    db.add(db_calc)

    # Persist line results
    for lr in engine_result.line_results:
        # Convert interpretations if present
        interpretations_data = None
        if lr.interpretations:
            interpretations_data = [
                {
                    "interpretation_id": interp.interpretation_id,
                    "recalculated_amount_cents": interp.recalculated_amount_cents,
                    "assumptions": interp.assumptions,
                    "rule_id": interp.rule_id,
                    "line_id": interp.line_id,
                }
                for interp in lr.interpretations
            ]

        quarantined_data = None
        if lr.quarantined_events:
            quarantined_data = [
                {
                    "event_id": q.event_id,
                    "reason": q.reason,
                    "raw": q.raw,
                }
                for q in lr.quarantined_events
            ]

        db_lr = CalculationLineResult(
            calculation_id=calc_id,
            line_id=lr.line_id,
            result_id=lr.result_id,
            rule_id=lr.rule_id,
            original_amount_cents=lr.original_amount_cents,
            recalculated_amount_cents=lr.recalculated_amount_cents,
            difference_cents=lr.difference_cents,
            finding_type=FindingTypeDB(lr.finding_type.value),
            quantity_used=float(lr.quantity_used),
            exempt_quantity=float(lr.exempt_quantity),
            applied_discount_pct=float(lr.applied_discount_pct) if lr.applied_discount_pct is not None else None,
            applied_minimum_commit_cents=lr.applied_minimum_commit_cents,
            interpretations=interpretations_data,
            assumptions=lr.assumptions,
            explanation=lr.explanation,
            quarantined_events=quarantined_data,
        )
        db.add(db_lr)

    # Mark quarantined events in database
    for q in engine_result.quarantined_events:
        db.query(DBUsageEvent).filter(
            DBUsageEvent.case_id == case.id,
            DBUsageEvent.id == q.event_id,
        ).update({"is_quarantined": 1, "quarantine_reason": q.reason})

    # Append-only audit event
    audit_event = CaseEvent(
        case_id=case.id,
        event_type="CALCULATION_RUN",
        actor=actor,
        details={
            "calculation_id": calc_id,
            "engine_status": engine_result.status.value,
            "total_difference_cents": engine_result.total_difference_cents,
            "result_hash": engine_result.result_hash,
            "evidence_version": case.evidence_version,
        },
        correlation_id=correlation_id,
    )
    db.add(audit_event)

    db.commit()
    db.refresh(db_calc)
    return db_calc
