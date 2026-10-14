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


def seed_demo_cases(db: Session, force: bool = False) -> list[str]:
    """
    Creates demo cases (including Scenario A: Missing Evidence, Scenario B: Verified Tier Overcharge,
    Bravo: Ambiguous Clause, Delta: Clean Invoice).
    If force=True, clears and re-creates demo cases.
    """
    demo_ids = [
        "case-acme-unverified",
        "case-acme-verified",
        "case-acme-101",
        "case-bravo-102",
        "case-delta-103",
    ]
    if not force and db.query(Case).count() > 0:
        logger.info("seed: database already has cases - skipping demo seed")
        return []

    if force:
        logger.info("seed: force=True - resetting demo cases")
        is_sqlite = db.bind is not None and db.bind.dialect.name == "sqlite"
        if is_sqlite:
            for trg in [
                "trg_case_events_no_delete",
                "trg_calc_results_no_delete",
                "trg_credits_no_delete",
                "trg_finding_reviews_no_delete",
                "trg_evidence_versions_no_delete",
                "trg_findings_no_delete",
            ]:
                try:
                    db.execute(text(f"DROP TRIGGER IF EXISTS {trg};"))
                except Exception:
                    pass
            db.commit()

        for cid in demo_ids:
            existing = db.query(Case).filter(Case.id == cid).first()
            if existing:
                db.delete(existing)
        db.commit()

        if is_sqlite:
            from app.database import install_append_only_triggers
            install_append_only_triggers(db.bind)

    logger.info("seed: seeding demo cases")
    now = datetime.now(timezone.utc)
    seeded = []

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO A: Acme Analytics Ltd. — Missing Evidence
    # ─────────────────────────────────────────────────────────────────────────
    c_scen_a = Case(
        id="case-acme-unverified",
        title="API Tier Rate Dispute — Awaiting Telemetry Evidence",
        customer_name="Acme Analytics Ltd.",
        invoice_id="INV-2026-ACME-001",
        currency="USD",
        claimed_usage_quantity=1200.0,
        claimed_usage_uom="API Calls",
        disputed_amount_cents=136000,
        dispute_description=(
            "We were billed $1,850.00 for 1,200 API calls, but our contract specifies tiered pricing: "
            "first 500 calls included ($0), calls 501–1,000 at $0.80 each, and calls above 1,000 at $0.45 each. "
            "We also believe a previous $100.00 credit was not applied to this account. "
            "Please credit the discrepancy immediately."
        ),
        status=CaseStatus.OPEN.value,
        evidence_version=1,
    )
    db.add(c_scen_a)
    db.flush()

    line_scen_a = InvoiceLine(
        id="line-acme-calls-unverified",
        case_id=c_scen_a.id,
        description="Production API Ingestion Calls",
        original_amount_cents=185000,
    )
    db.add(line_scen_a)
    db.flush()

    db.add(ContractRule(
        id="rule-acme-tiers-unverified",
        case_id=c_scen_a.id,
        line_id=line_scen_a.id,
        rule_type="TIERED_GRADUATED",
        rate_cents=0,
        tiers=[
            {"up_to": 500, "price_per_unit_cents": 0},
            {"up_to": 1000, "price_per_unit_cents": 80},
            {"up_to": None, "price_per_unit_cents": 45},
        ],
        exempt_environments=["staging", "test"],
    ))

    # Alleged unverified prior credit from customer statement (is_verified=False)
    db.add(Adjustment(
        id="adj-acme-alleged-100",
        case_id=c_scen_a.id,
        invoice_line_id=line_scen_a.id,
        amount_cents=10000,
        description="Customer statement alleges unapplied prior billing credit",
        is_verified=False,
        evidence_source="Customer Statement (Unverified Claim)",
    ))
    db.flush()

    # Zero telemetry events persisted for Scenario A!
    rules_a = db.query(ContractRule).filter(ContractRule.case_id == c_scen_a.id).all()
    lines_a = db.query(InvoiceLine).filter(InvoiceLine.case_id == c_scen_a.id).all()
    db.add(EvidenceVersion(
        case_id=c_scen_a.id,
        version_number=1,
        content_hash=_content_hash(lines_a, rules_a, []),
        created_by="SYSTEM",
    ))
    db.add(CaseEvent(
        case_id=c_scen_a.id,
        event_type="CASE_CREATED",
        actor="SYSTEM",
        details={"source": "seed", "scenario": "A_MISSING_EVIDENCE"},
    ))
    seeded.append(c_scen_a.id)

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO B: Acme Analytics Ltd. — Verified Tier Overcharge
    # ─────────────────────────────────────────────────────────────────────────
    c_scen_b = Case(
        id="case-acme-verified",
        title="Metered API Tier Overcharge — Verified Telemetry",
        customer_name="Acme Analytics Ltd.",
        invoice_id="INV-2026-ACME-002",
        currency="USD",
        claimed_usage_quantity=1200.0,
        claimed_usage_uom="API Calls",
        disputed_amount_cents=136000,
        dispute_description=(
            "Customer reports $1,360.00 overcharge on 1,200 API calls billed at $1,850.00. "
            "Verified telemetry confirms 1,200 production calls. "
            "Under graduated contract terms (first 500 @ $0, next 500 @ $0.80, remaining 200 @ $0.45), "
            "recalculated charge is $490.00, yielding a $1,360.00 overcharge."
        ),
        status=CaseStatus.OPEN.value,
        evidence_version=1,
    )
    db.add(c_scen_b)
    db.flush()

    line_scen_b = InvoiceLine(
        id="line-acme-calls-verified",
        case_id=c_scen_b.id,
        description="Production API Ingestion Calls",
        original_amount_cents=185000,
    )
    db.add(line_scen_b)
    db.flush()

    db.add(ContractRule(
        id="rule-acme-tiers-verified",
        case_id=c_scen_b.id,
        line_id=line_scen_b.id,
        rule_type="TIERED_GRADUATED",
        rate_cents=0,
        tiers=[
            {"up_to": 500, "price_per_unit_cents": 0},
            {"up_to": 1000, "price_per_unit_cents": 80},
            {"up_to": None, "price_per_unit_cents": 45},
        ],
        exempt_environments=["staging", "test"],
    ))

    # 1,200 verified production usage calls
    db.add(UsageEvent(
        id="ev-acme-verified-prod-1",
        case_id=c_scen_b.id,
        line_id=line_scen_b.id,
        quantity=1200.0,
        environment="production",
        event_timestamp=now,
    ))
    db.flush()

    rules_b = db.query(ContractRule).filter(ContractRule.case_id == c_scen_b.id).all()
    events_b = db.query(UsageEvent).filter(UsageEvent.case_id == c_scen_b.id).all()
    lines_b = db.query(InvoiceLine).filter(InvoiceLine.case_id == c_scen_b.id).all()
    db.add(EvidenceVersion(
        case_id=c_scen_b.id,
        version_number=1,
        content_hash=_content_hash(lines_b, rules_b, events_b),
        created_by="SYSTEM",
    ))
    db.add(CaseEvent(
        case_id=c_scen_b.id,
        event_type="CASE_CREATED",
        actor="SYSTEM",
        details={"source": "seed", "scenario": "B_VERIFIED_OVERCHARGE"},
    ))
    seeded.append(c_scen_b.id)

    # ─────────────────────────────────────────────────────────────────────────
    # Legacy / Additional Demo Cases
    # ─────────────────────────────────────────────────────────────────────────
    # 1. Acme Corp - PER_UNIT overcharge
    c1 = Case(
        id="case-acme-101",
        title="Metered API Tier Overcharge (Staging Exemption)",
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

    db.add(Adjustment(
        id="adj-acme-1",
        case_id=c1.id,
        invoice_line_id="line-api-calls",
        amount_cents=500,
        description="Partial goodwill credit applied by account team before dispute filing",
        is_verified=True,
    ))
    db.flush()

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
    seeded.append(c1.id)

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
    logger.info("seed: successfully created demo cases (acme-unverified, acme-verified, acme-101, bravo-102, delta-103)")
    return seeded


def seed_demo_cases_if_empty(db: Session) -> None:
    """Creates demo cases when the cases table is empty."""
    seed_demo_cases(db, force=False)
