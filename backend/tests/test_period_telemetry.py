"""
test_period_telemetry.py
========================
Tests for Task 4:
Billing period vs telemetry timestamp (prevent silent INSUFFICIENT_DATA).

When a period is given, telemetry events stamped within the period (e.g. noon UTC on period start)
must never be quarantined as 'Outside billing period', and must successfully calculate (engine_status == OK)
across:
  - Past billing period
  - Current billing period
  - Future billing period
  - No billing period (None / None)

Also tests that if an event IS outside the billing period, it is properly quarantined with
reason "Outside billing period" and yields INSUFFICIENT_DATA.
"""

from datetime import datetime, timezone
from decimal import Decimal
import pytest

from app.billing_engine import (
    ContractRule,
    EngineStatus,
    FindingType,
    InvoiceLine,
    RuleType,
    TierBand,
    UsageEvent,
    run_calculation,
)


@pytest.mark.parametrize(
    "period_start_str,period_end_str,event_ts_str,desc",
    [
        # Past period: Jan 2023
        ("2023-01-01T00:00:00Z", "2023-01-31T23:59:59Z", "2023-01-01T12:00:00Z", "past period"),
        # Current period: Oct 2026
        ("2026-10-01T00:00:00Z", "2026-10-31T23:59:59Z", "2026-10-01T12:00:00Z", "current period"),
        # Future period: Jan 2029
        ("2029-01-01T00:00:00Z", "2029-01-31T23:59:59Z", "2029-01-01T12:00:00Z", "future period"),
        # No period specified
        (None, None, "2026-10-15T12:00:00Z", "no period"),
    ],
)
def test_telemetry_within_period_produces_ok(period_start_str, period_end_str, event_ts_str, desc):
    """
    Parametrized test for Task 4: past, current, future, and no period
    all produce EngineStatus.OK with entered telemetry stamped within the period.
    """
    line_id = "line-1"
    line = InvoiceLine(
        line_id=line_id,
        description="Compute Tiered",
        original_amount_cents=125000,
    )
    rule = ContractRule(
        rule_id="rule-1",
        line_id=line_id,
        rule_type=RuleType.TIERED_GRADUATED,
        tiers=[
            TierBand(price_per_unit_cents=0, up_to=500),
            TierBand(price_per_unit_cents=80, up_to=1000),
            TierBand(price_per_unit_cents=45, up_to=None),
        ],
        exempt_environments=["staging"],
    )

    ev_ts = datetime.fromisoformat(event_ts_str.replace("Z", "+00:00"))
    event = UsageEvent(
        event_id="ev-1",
        line_id=line_id,
        quantity=Decimal("1800"),
        environment="production",
        timestamp=ev_ts,
    )

    result = run_calculation(
        rules=[rule],
        lines=[line],
        events=[event],
        period_start=period_start_str,
        period_end=period_end_str,
    )

    assert result.status == EngineStatus.OK, f"Failed for {desc}: got {result.engine_status}"
    assert len(result.quarantined_events) == 0, f"Quarantined unexpected events: {result.quarantined_events}"
    assert result.total_recalculated_cents == 76000
    assert result.total_difference_cents == -49000
    assert result.line_results[0].finding_type == FindingType.CONFIRMED_CALCULATION_DISCREPANCY


def test_telemetry_outside_period_quarantined_with_reason():
    """
    Test that when an event timestamp is strictly outside the billing period,
    it is correctly quarantined with 'Outside billing period' and yields INSUFFICIENT_DATA.
    """
    line_id = "line-1"
    line = InvoiceLine(
        line_id=line_id,
        description="Compute Tiered",
        original_amount_cents=125000,
    )
    rule = ContractRule(
        rule_id="rule-1",
        line_id=line_id,
        rule_type=RuleType.TIERED_GRADUATED,
        tiers=[
            TierBand(price_per_unit_cents=0, up_to=500),
            TierBand(price_per_unit_cents=80, up_to=1000),
            TierBand(price_per_unit_cents=45, up_to=None),
        ],
    )

    # Event timestamp in 2026, but billing period was in 2024
    ev_ts = datetime(2026, 10, 15, 12, 0, 0, tzinfo=timezone.utc)
    event = UsageEvent(
        event_id="ev-1",
        line_id=line_id,
        quantity=Decimal("1800"),
        environment="production",
        timestamp=ev_ts,
        raw={"event_id": "ev-1"},
    )

    result = run_calculation(
        rules=[rule],
        lines=[line],
        events=[event],
        period_start="2024-01-01T00:00:00Z",
        period_end="2024-01-31T23:59:59Z",
    )

    assert result.status == EngineStatus.INSUFFICIENT_DATA
    assert len(result.quarantined_events) == 1
    assert result.quarantined_events[0].reason == "Outside billing period"
    assert result.quarantined_events[0].event_id == "ev-1"
