"""
seed.py
=======
Demo data seeder for FairBill.

Provides seed_demo_cases_if_empty(db) which creates three representative
billing-dispute cases when the database is completely empty.

Cases:
  case-acme-101  - PER_UNIT overcharge (staging events exempt but billed).
                   Expected engine result: CONFIRMED_CALCULATION_DISCREPANCY.
  case-bravo-102 - TIERED_GRADUATED + TIERED_VOLUME competing rules.
                   Expected engine result: AMBIGUOUS (two interpretations).
  case-delta-103 - FLAT fee, billed exactly per contract.
                   Expected engine result: NO_DISCREPANCY.

This module is the single source of truth for demo data.
backend/seed_demo_data.py imports from here so there is no duplication.
"""

import hashlib
import json
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.case import Case, CaseEvent, CaseStatus
from app.models.invoice import ContractRule, InvoiceLine
from app.models.usage import EvidenceVersion, UsageEvent
from app.models.credit import Adjustment

logger = logging.getLogger(__name__)


def _content_hash(lines, rules, events) -> str:
    """SHA-256 hash of serialised evidence - mirrors transition_service logic."""
    payload = json.dumps(
        {
            "lines": sorted(
                [{"id": l.id, "original_amount_cents": l.original_amount_cents} for l in lines],
                key=lambda x: x["id"],
            ),
            "rules": sorted(
                [{"id": r.id, "rule_type": str(r.rule_type), "rate_cents": r.rate_cents} for r in rules],
                key=lambda x: x["id"],
            ),
            "events": sorted(
                [{"id": e.id, "quantity": float(e.quantity), "environment": e.environment} for e in events],
                key=lambda x: x["id"],
            ),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def seed_demo_cases_if_empty(db: Session) -> None:
    """
    Creates three demo cases when the cases table is empty.
    Idempotent - does nothing if any case rows already exist.
    """
    if db.query(Case).count() > 0:
        logger.info("seed: database already has cases - skipping demo seed")
        return

    logger.info("seed: empty database detected - seeding 3 demo cases")
    now = datetime.now(timezone.utc)

    # 1. Acme Corp - PER_UNIT overcharge
    c1 = Case(
        id="case-acme-101",
        title="Metered API Tier Overcharge",
        customer_name="Acme Corp",
        disputed_amount_cents=2500,
        dispute_description=(
            "Customer reports overcharge of $25.00 on production API calls. "
            "Telemetry logs show 250 production calls and 150 staging calls; "
            "staging calls were improperly counted towards billable tier."
        ),
        status=CaseStatus.OPEN.value,
        evidence_version=1,
    )
    db.add(c1)
    db.flush()

    line_acme = InvoiceLine(
        id="line-api-calls",
        case_id=c1.id,
        description="Production API Metered Requests",
        original_amount_cents=5000,
    )
    db.add(line_acme)
    db.flush()

    db.add(ContractRule(
        id="rule-api-rate",
        case_id=c1.id,
        line_id="line-api-calls",
        rule_type="PER_UNIT",
        rate_cents=10,
        exempt_environments=["staging", "test"],
    ))

    db.add(UsageEvent(
        id="ev-acme-prod-1",
        case_id=c1.id,
        line_id="line-api-calls",
        quantity=250.0,
        environment="production",
        event_timestamp=now,
    ))
    db.add(UsageEvent(
        id="ev-acme-stg-1",
        case_id=c1.id,
        line_id="line-api-calls",
        quantity=150.0,
        environment="staging",
        event_timestamp=now,
    ))
    db.flush()

    # Prior adjustment (500c) so cap logic is demonstrable
    db.add(Adjustment(
        id="adj-acme-1",
        case_id=c1.id,
        invoice_line_id="line-api-calls",
        amount_cents=500,
        description="Partial goodwill credit applied by account team before dispute filing",
    ))
    db.flush()

    # EvidenceVersion snapshot (version 1)
    rules_acme = db.query(ContractRule).filter(ContractRule.case_id == c1.id).all()
    events_acme = db.query(UsageEvent).filter(UsageEvent.case_id == c1.id).all()
    lines_acme = db.query(InvoiceLine).filter(InvoiceLine.case_id == c1.id).all()
    db.add(EvidenceVersion(
        case_id=c1.id,
        version_number=1,
        content_hash=_content_hash(lines_acme, rules_acme, events_acme),
        created_by="SYSTEM",
    ))

    db.add(CaseEvent(
        case_id=c1.id,
        event_type="CASE_CREATED",
        actor="SYSTEM",
        details={"source": "seed", "title": c1.title},
    ))

    # 2. Bravo Ltd - Ambiguous tier interpretation
    c2 = Case(
        id="case-bravo-102",
        title="Underspecified Tiered Pricing Clause",
        customer_name="Bravo Ltd",
        disputed_amount_cents=1500,
        dispute_description=(
            "Dispute regarding tier calculation method on 200 compute units. "
            "Contract rule card contains competing graduated and volume interpretations."
        ),
        status=CaseStatus.OPEN.value,
        evidence_version=1,
    )
    db.add(c2)
    db.flush()

    line_bravo = InvoiceLine(
        id="line-compute-units",
        case_id=c2.id,
        description="Compute Units Band A",
        original_amount_cents=4000,
    )
    db.add(line_bravo)
    db.flush()

    db.add(ContractRule(
        id="rule-tiered-grad",
        case_id=c2.id,
        line_id="line-compute-units",
        rule_type="TIERED_GRADUATED",
        rate_cents=0,
        tiers=[
            {"up_to": 100, "price_per_unit_cents": 15},
            {"up_to": None, "price_per_unit_cents": 10},
        ],
    ))
    db.add(ContractRule(
        id="rule-tiered-vol",
        case_id=c2.id,
        line_id="line-compute-units",
        rule_type="TIERED_VOLUME",
        rate_cents=0,
        tiers=[
            {"up_to": 100, "price_per_unit_cents": 15},
            {"up_to": None, "price_per_unit_cents": 10},
        ],
    ))

    db.add(UsageEvent(
        id="ev-bravo-1",
        case_id=c2.id,
        line_id="line-compute-units",
        quantity=200.0,
        environment="production",
        event_timestamp=now,
    ))
    db.flush()

    rules_bravo = db.query(ContractRule).filter(ContractRule.case_id == c2.id).all()
    events_bravo = db.query(UsageEvent).filter(UsageEvent.case_id == c2.id).all()
    lines_bravo = db.query(InvoiceLine).filter(InvoiceLine.case_id == c2.id).all()
    db.add(EvidenceVersion(
        case_id=c2.id,
        version_number=1,
        content_hash=_content_hash(lines_bravo, rules_bravo, events_bravo),
        created_by="SYSTEM",
    ))

    db.add(CaseEvent(
        case_id=c2.id,
        event_type="CASE_CREATED",
        actor="SYSTEM",
        details={"source": "seed", "title": c2.title},
    ))

    # 3. Delta Cloud - FLAT fee, clean invoice
    c3 = Case(
        id="case-delta-103",
        title="Clean Fixed Platform Subscription",
        customer_name="Delta Cloud",
        disputed_amount_cents=0,
        dispute_description=(
            "Customer inquiry regarding $100.00 base platform subscription fee. "
            "Recalculation confirms billed amount is exact per flat contract rule."
        ),
        status=CaseStatus.OPEN.value,
        evidence_version=1,
    )
    db.add(c3)
    db.flush()

    line_delta = InvoiceLine(
        id="line-platform-sub",
        case_id=c3.id,
        description="Monthly Platform Fee",
        original_amount_cents=10000,
    )
    db.add(line_delta)
    db.flush()

    db.add(ContractRule(
        id="rule-sub-flat",
        case_id=c3.id,
        line_id="line-platform-sub",
        rule_type="FLAT",
        rate_cents=10000,
    ))
    db.flush()

    rules_delta = db.query(ContractRule).filter(ContractRule.case_id == c3.id).all()
    events_delta = db.query(UsageEvent).filter(UsageEvent.case_id == c3.id).all()
    lines_delta = db.query(InvoiceLine).filter(InvoiceLine.case_id == c3.id).all()
    db.add(EvidenceVersion(
        case_id=c3.id,
        version_number=1,
        content_hash=_content_hash(lines_delta, rules_delta, events_delta),
        created_by="SYSTEM",
    ))

    db.add(CaseEvent(
        case_id=c3.id,
        event_type="CASE_CREATED",
        actor="SYSTEM",
        details={"source": "seed", "title": c3.title},
    ))

    db.commit()
    logger.info("seed: successfully created 3 demo cases (acme-101, bravo-102, delta-103)")
