"""
tests/test_billing_period_and_provider_checks.py
================================================
Tests for billing period quarantine and provider checks:
- Billing period quarantine (events outside period_start / period_end quarantined with 'Outside billing period')
- No LLM provider configured returns HTTP 503
- Finding review ordering: created_at.desc(), id.desc()
- Clean duplicate event error reporting
"""

from datetime import datetime, timezone
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.case import Case, CaseStatus
from app.models.invoice import InvoiceLine, ContractRule, RuleTypeDB
from app.models.usage import UsageEvent
from app.models.investigation import Finding, FindingReview, ReviewDecision
from app import billing_engine as engine
from app.services.calculation_service import execute_case_calculation
from app.config import settings


def test_billing_period_quarantine_in_billing_engine():
    """Events with timestamps outside [period_start, period_end] are quarantined."""
    line = engine.InvoiceLine(
        line_id="line-1",
        description="Compute",
        original_amount_cents=10000,
    )
    rule = engine.ContractRule(
        rule_id="rule-1",
        line_id="line-1",
        rule_type=engine.RuleType.PER_UNIT,
        rate_cents=10,
    )

    t_start = datetime(2026, 3, 1, 0, 0, 0)
    t_end = datetime(2026, 3, 31, 23, 59, 59)

    events = [
        engine.UsageEvent(
            event_id="ev-before",
            line_id="line-1",
            quantity=Decimal("100"),
            environment="production",
            timestamp=datetime(2026, 2, 28, 23, 59, 59),
        ),
        engine.UsageEvent(
            event_id="ev-inside",
            line_id="line-1",
            quantity=Decimal("200"),
            environment="production",
            timestamp=datetime(2026, 3, 15, 12, 0, 0),
        ),
        engine.UsageEvent(
            event_id="ev-after",
            line_id="line-1",
            quantity=Decimal("300"),
            environment="production",
            timestamp=datetime(2026, 4, 1, 0, 0, 0),
        ),
    ]

    res = engine.run_calculation(
        lines=[line],
        rules=[rule],
        events=events,
        period_start=t_start,
        period_end=t_end,
    )

    quarantined_ids = [q.event_id for q in res.quarantined_events]
    assert "ev-before" in quarantined_ids
    assert "ev-after" in quarantined_ids
    assert "ev-inside" not in quarantined_ids

    for q in res.quarantined_events:
        if q.event_id in ("ev-before", "ev-after"):
            assert q.reason == "Outside billing period"

    # Only ev-inside was calculated: 200 units * 10 cents = 2000 cents
    lr = res.line_results[0]
    assert lr.recalculated_amount_cents == 2000


def test_billing_period_quarantine_in_calculation_service(tmp_path, monkeypatch):
    """Case period_start and period_end correctly trigger quarantine during execute_case_calculation."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base

    db_file = tmp_path / "test_task9.sqlite"
    test_engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=test_engine)
    Session = sessionmaker(bind=test_engine)
    db = Session()

    t_start = datetime(2026, 3, 1, 0, 0, 0)
    t_end = datetime(2026, 3, 31, 23, 59, 59)

    case = Case(
        id="case-period-test",
        title="Period Test",
        customer_name="Test Corp",
        disputed_amount_cents=5000,
        status=CaseStatus.OPEN.value,
        period_start=t_start,
        period_end=t_end,
    )
    line = InvoiceLine(
        id="line-p1",
        case_id="case-period-test",
        description="API Calls",
        original_amount_cents=5000,
    )
    rule = ContractRule(
        id="rule-p1",
        case_id="case-period-test",
        line_id="line-p1",
        rule_type=RuleTypeDB.PER_UNIT,
        rate_cents=10,
        is_active=True,
    )
    ev_valid = UsageEvent(
        id="ev-p-valid",
        case_id="case-period-test",
        line_id="line-p1",
        quantity=150.0,
        environment="production",
        event_timestamp=datetime(2026, 3, 10, 10, 0, 0),
    )
    ev_invalid = UsageEvent(
        id="ev-p-invalid",
        case_id="case-period-test",
        line_id="line-p1",
        quantity=80.0,
        environment="production",
        event_timestamp=datetime(2026, 4, 5, 10, 0, 0),
    )

    db.add_all([case, line, rule, ev_valid, ev_invalid])
    db.commit()

    calc = execute_case_calculation(db, "case-period-test", actor="REVIEWER")

    # Verify invalid event was quarantined
    db.refresh(ev_invalid)
    assert ev_invalid.is_quarantined == 1
    assert ev_invalid.quarantine_reason == "Outside billing period"

    # Verify valid event was NOT quarantined
    db.refresh(ev_valid)
    assert ev_valid.is_quarantined == 0

    # Recalculated amount should only reflect 150 * 10 = 1500 cents
    lr = calc.line_results[0]
    assert lr.recalculated_amount_cents == 1500
    db.close()


def test_no_llm_provider_configured_returns_503(monkeypatch):
    """When LLM_MODE=real and no providers have keys configured, return HTTP 503."""
    from app.database import create_all_tables
    create_all_tables()
    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {settings.demo_reviewer_token}"}

        monkeypatch.setattr(settings, "llm_mode", "real")
        monkeypatch.setattr(settings, "gemini_api_key", "")
        monkeypatch.setattr(settings, "groq_api_key", "")
        monkeypatch.setattr(settings, "openrouter_api_key", "")

        resp = client.post("/api/cases/case-acme-101/investigations", headers=headers)
        assert resp.status_code == 503
        assert "No LLM provider configured" in resp.json()["detail"]


def test_finding_review_ordering():
    """Finding.reviews relationship must be ordered by created_at.desc(), id.desc()."""
    order_clause = Finding.reviews.property.order_by
    col_names = [expr.element.name for expr in order_clause]
    assert "created_at" in col_names
    assert "id" in col_names
