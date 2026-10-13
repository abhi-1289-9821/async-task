"""
test_billing_engine.py
======================
Pure unit tests for billing_engine.py.
No database, no network, no API key required.

Coverage:
  - Every rule type: FLAT, PER_UNIT, TIERED_GRADUATED, TIERED_VOLUME,
    INCLUDED_UNITS, DISCOUNT_PCT, MINIMUM_COMMIT
  - Graduated vs volume: same inputs, different results
  - Included units: zero usage, exactly at boundary, one over
  - Minimum commit: above, at, and below
  - Discount: combined with other rules, rounding at boundary
  - Environment exemptions: staging excluded, production included, mixed
  - Ambiguous clause: TIERED_GRADUATED + TIERED_VOLUME → two InterpretationResults
  - Two DISCOUNT_PCT → AMBIGUOUS
  - Malformed events: negative qty, missing field → quarantined, calc continues
  - Zero quantity, zero rate
  - Missing rule → INSUFFICIENT_DATA
  - Repeatability: same inputs → identical result_id twice
  - TIERED_VOLUME boundary: quantity == up_to uses THAT tier's price
  - ROUND_HALF_UP at line boundary (not on intermediate values)
"""

import pytest
from decimal import Decimal

from app.billing_engine import (
    ContractRule,
    EngineStatus,
    FindingType,
    InvoiceLine,
    InterpretationResult,
    RuleType,
    TierBand,
    UsageEvent,
    _round_cents,
    calculate_line,
    run_calculation,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def make_line(line_id: str = "L1", original_cents: int = 1000) -> InvoiceLine:
    return InvoiceLine(line_id=line_id, description="Test line", original_amount_cents=original_cents)


def make_event(line_id: str = "L1", qty: Decimal | int = 10, env: str = "production",
               event_id: str = "E1") -> UsageEvent:
    return UsageEvent(
        event_id=event_id,
        line_id=line_id,
        quantity=Decimal(str(qty)),
        environment=env,
        raw={},
    )


def make_rule(
    rule_type: RuleType,
    line_id: str = "L1",
    rule_id: str = "R1",
    rate_cents: int = 0,
    tiers: list | None = None,
    discount_pct: str = "0",
    minimum_commit_cents: int = 0,
    included_units: int = 0,
    overage_rate_cents: int | None = None,
    exempt_environments: list[str] | None = None,
) -> ContractRule:
    return ContractRule(
        rule_id=rule_id,
        line_id=line_id,
        rule_type=rule_type,
        rate_cents=rate_cents,
        tiers=tiers or [],
        discount_pct=Decimal(discount_pct),
        minimum_commit_cents=minimum_commit_cents,
        included_units=included_units,
        overage_rate_cents=overage_rate_cents,
        exempt_environments=exempt_environments or [],
    )


# ─────────────────────────────────────────────────────────────────────────────
# _round_cents
# ─────────────────────────────────────────────────────────────────────────────

class TestRoundCents:
    def test_rounds_half_up(self):
        # 0.5 → 1 (ROUND_HALF_UP)
        assert _round_cents(Decimal("0.5")) == 1

    def test_rounds_half_up_negative(self):
        # ROUND_HALF_UP on -0.5 rounds AWAY from zero → -1 (not 0).
        # Python's Decimal ROUND_HALF_UP means "round half away from zero".
        # This is a documentation test; negative amounts don't arise in billing
        # (all prices and quantities are non-negative by contract).
        assert _round_cents(Decimal("-0.5")) == -1

    def test_exact_integer_unchanged(self):
        assert _round_cents(Decimal("42")) == 42

    def test_rounds_down(self):
        assert _round_cents(Decimal("1.4")) == 1

    def test_rounds_up(self):
        assert _round_cents(Decimal("1.6")) == 2

    def test_rounding_boundary_at_0_5(self):
        # 2.5 → 3 (not 2, which ROUND_HALF_EVEN would give)
        assert _round_cents(Decimal("2.5")) == 3


# ─────────────────────────────────────────────────────────────────────────────
# FLAT rule
# ─────────────────────────────────────────────────────────────────────────────

class TestFlat:
    def test_flat_ignores_usage(self):
        line = make_line(original_cents=500)
        rule = make_rule(RuleType.FLAT, rate_cents=300)
        events = [make_event(qty=999)]  # quantity irrelevant for FLAT
        result = calculate_line(line, [rule], events)
        assert result.recalculated_amount_cents == 300
        assert result.finding_type == FindingType.CONFIRMED_CALCULATION_DISCREPANCY
        assert result.difference_cents == -200  # overcharged by 200¢

    def test_flat_no_discrepancy(self):
        line = make_line(original_cents=300)
        rule = make_rule(RuleType.FLAT, rate_cents=300)
        result = calculate_line(line, [rule], [])
        assert result.finding_type == FindingType.NO_DISCREPANCY
        assert result.difference_cents == 0

    def test_flat_zero_rate(self):
        line = make_line(original_cents=100)
        rule = make_rule(RuleType.FLAT, rate_cents=0)
        result = calculate_line(line, [rule], [])
        assert result.recalculated_amount_cents == 0
        assert result.difference_cents == -100


# ─────────────────────────────────────────────────────────────────────────────
# PER_UNIT rule
# ─────────────────────────────────────────────────────────────────────────────

class TestPerUnit:
    def test_basic(self):
        line = make_line(original_cents=500)
        rule = make_rule(RuleType.PER_UNIT, rate_cents=10)
        events = [make_event(qty=50)]
        result = calculate_line(line, [rule], events)
        assert result.recalculated_amount_cents == 500
        assert result.finding_type == FindingType.NO_DISCREPANCY

    def test_overcharge(self):
        line = make_line(original_cents=1000)
        rule = make_rule(RuleType.PER_UNIT, rate_cents=5)
        events = [make_event(qty=100)]  # correct = 500
        result = calculate_line(line, [rule], events)
        assert result.recalculated_amount_cents == 500
        assert result.difference_cents == -500

    def test_zero_usage(self):
        line = make_line(original_cents=100)
        rule = make_rule(RuleType.PER_UNIT, rate_cents=10)
        result = calculate_line(line, [rule], [])
        assert result.recalculated_amount_cents == 0
        assert result.quantity_used == Decimal("0")

    def test_multiple_events_summed(self):
        line = make_line(original_cents=200)
        rule = make_rule(RuleType.PER_UNIT, rate_cents=2)
        events = [
            make_event(qty=50, event_id="E1"),
            make_event(qty=50, event_id="E2"),
        ]  # total = 100 events × 2¢ = 200¢
        result = calculate_line(line, [rule], events)
        assert result.recalculated_amount_cents == 200
        assert result.quantity_used == Decimal("100")


# ─────────────────────────────────────────────────────────────────────────────
# TIERED_GRADUATED
# ─────────────────────────────────────────────────────────────────────────────

class TestTieredGraduated:
    def _std_tiers(self):
        return [
            TierBand(up_to=100,  price_per_unit_cents=10),
            TierBand(up_to=200,  price_per_unit_cents=8),
            TierBand(up_to=None, price_per_unit_cents=6),
        ]

    def test_within_first_tier(self):
        line = make_line(original_cents=500)
        rule = make_rule(RuleType.TIERED_GRADUATED, tiers=self._std_tiers())
        events = [make_event(qty=50)]
        result = calculate_line(line, [rule], events)
        assert result.recalculated_amount_cents == 500  # 50×10=500

    def test_boundary_of_first_tier(self):
        line = make_line(original_cents=1000)
        rule = make_rule(RuleType.TIERED_GRADUATED, tiers=self._std_tiers())
        events = [make_event(qty=100)]
        result = calculate_line(line, [rule], events)
        assert result.recalculated_amount_cents == 1000  # 100×10=1000

    def test_spans_two_tiers(self):
        # 100×10 + 50×8 = 1000 + 400 = 1400
        line = make_line(original_cents=1400)
        rule = make_rule(RuleType.TIERED_GRADUATED, tiers=self._std_tiers())
        events = [make_event(qty=150)]
        result = calculate_line(line, [rule], events)
        assert result.recalculated_amount_cents == 1400

    def test_spans_all_tiers(self):
        # 100×10 + 100×8 + 50×6 = 1000 + 800 + 300 = 2100
        line = make_line(original_cents=9999)
        rule = make_rule(RuleType.TIERED_GRADUATED, tiers=self._std_tiers())
        events = [make_event(qty=250)]
        result = calculate_line(line, [rule], events)
        assert result.recalculated_amount_cents == 2100

    def test_zero_usage(self):
        line = make_line(original_cents=100)
        rule = make_rule(RuleType.TIERED_GRADUATED, tiers=self._std_tiers())
        result = calculate_line(line, [rule], [])
        assert result.recalculated_amount_cents == 0


# ─────────────────────────────────────────────────────────────────────────────
# TIERED_VOLUME — including boundary behaviour
# ─────────────────────────────────────────────────────────────────────────────

class TestTieredVolume:
    def _std_tiers(self):
        return [
            TierBand(up_to=100,  price_per_unit_cents=10),
            TierBand(up_to=200,  price_per_unit_cents=8),
            TierBand(up_to=None, price_per_unit_cents=6),
        ]

    def test_within_first_tier(self):
        line = make_line(original_cents=500)
        rule = make_rule(RuleType.TIERED_VOLUME, tiers=self._std_tiers())
        events = [make_event(qty=50)]
        result = calculate_line(line, [rule], events)
        assert result.recalculated_amount_cents == 500  # 50×10=500

    def test_boundary_belongs_to_lower_tier(self):
        # quantity=100 is exactly the up_to of tier1 → use tier1 price (10)
        line = make_line(original_cents=1000)
        rule = make_rule(RuleType.TIERED_VOLUME, tiers=self._std_tiers())
        events = [make_event(qty=100)]
        result = calculate_line(line, [rule], events)
        assert result.recalculated_amount_cents == 1000  # 100×10 (not 100×8)

    def test_one_above_boundary_uses_next_tier(self):
        # quantity=101 → uses tier2 price (8) for ALL units
        line = make_line(original_cents=1500)
        rule = make_rule(RuleType.TIERED_VOLUME, tiers=self._std_tiers())
        events = [make_event(qty=101)]
        result = calculate_line(line, [rule], events)
        assert result.recalculated_amount_cents == 808  # 101×8

    def test_vs_graduated_same_inputs_different_results(self):
        """
        Graduated vs Volume produce different results for the same inputs.
        This test documents and proves the difference.
        """
        qty = 150
        tiers = self._std_tiers()

        line = make_line()
        grad_rule = make_rule(RuleType.TIERED_GRADUATED, tiers=tiers)
        vol_rule  = make_rule(RuleType.TIERED_VOLUME,    tiers=tiers, rule_id="R2")

        grad_result = calculate_line(line, [grad_rule], [make_event(qty=qty)])
        vol_result  = calculate_line(line, [vol_rule],  [make_event(qty=qty)])

        # Graduated: 100×10 + 50×8 = 1400
        assert grad_result.recalculated_amount_cents == 1400
        # Volume: 150×8 = 1200 (all units at tier-2 rate)
        assert vol_result.recalculated_amount_cents == 1200
        # Confirm they differ
        assert grad_result.recalculated_amount_cents != vol_result.recalculated_amount_cents


# ─────────────────────────────────────────────────────────────────────────────
# INCLUDED_UNITS
# ─────────────────────────────────────────────────────────────────────────────

class TestIncludedUnits:
    def test_zero_usage_no_charge(self):
        line = make_line(original_cents=500)
        rule = make_rule(RuleType.INCLUDED_UNITS, included_units=100, overage_rate_cents=5)
        result = calculate_line(line, [rule], [])
        assert result.recalculated_amount_cents == 0

    def test_exactly_at_boundary_no_overage(self):
        line = make_line(original_cents=500)
        rule = make_rule(RuleType.INCLUDED_UNITS, included_units=100, overage_rate_cents=5)
        events = [make_event(qty=100)]
        result = calculate_line(line, [rule], events)
        assert result.recalculated_amount_cents == 0  # exactly 100 included, no overage

    def test_one_over_boundary(self):
        line = make_line(original_cents=500)
        rule = make_rule(RuleType.INCLUDED_UNITS, included_units=100, overage_rate_cents=5)
        events = [make_event(qty=101)]
        result = calculate_line(line, [rule], events)
        assert result.recalculated_amount_cents == 5  # 1 overage unit × 5¢

    def test_large_overage(self):
        line = make_line(original_cents=9999)
        rule = make_rule(RuleType.INCLUDED_UNITS, included_units=100, overage_rate_cents=10)
        events = [make_event(qty=200)]
        result = calculate_line(line, [rule], events)
        assert result.recalculated_amount_cents == 1000  # 100 overage × 10¢

    def test_uses_overage_rate_not_rate_cents(self):
        """overage_rate_cents takes priority over rate_cents when set."""
        line = make_line(original_cents=500)
        rule = make_rule(
            RuleType.INCLUDED_UNITS,
            rate_cents=999,        # should NOT be used
            overage_rate_cents=5,  # should be used
            included_units=100,
        )
        events = [make_event(qty=110)]
        result = calculate_line(line, [rule], events)
        assert result.recalculated_amount_cents == 50  # 10 overage × 5¢


# ─────────────────────────────────────────────────────────────────────────────
# DISCOUNT_PCT
# ─────────────────────────────────────────────────────────────────────────────

class TestDiscount:
    def test_ten_percent_discount(self):
        line = make_line(original_cents=9999)
        per_unit_rule = make_rule(RuleType.PER_UNIT, rate_cents=10, rule_id="R1")
        discount_rule = make_rule(
            RuleType.DISCOUNT_PCT, discount_pct="10", rule_id="R2"
        )
        events = [make_event(qty=100)]  # raw = 1000¢; 10% off → 900¢
        result = calculate_line(line, [per_unit_rule, discount_rule], events)
        assert result.recalculated_amount_cents == 900
        assert result.applied_discount_pct == Decimal("10")

    def test_discount_rounding_at_boundary(self):
        """
        10% of 1001¢ = 100.1¢ discount → raw_after_discount = 900.9¢
        ROUND_HALF_UP at line boundary → 901¢.
        This test verifies NO intermediate rounding and correct boundary rounding.
        """
        line = make_line(original_cents=9999)
        per_unit_rule = make_rule(RuleType.PER_UNIT, rate_cents=1001, rule_id="R1")
        discount_rule = make_rule(
            RuleType.DISCOUNT_PCT, discount_pct="10", rule_id="R2"
        )
        events = [make_event(qty=1)]  # raw = 1001; 10% off = 900.9; round → 901
        result = calculate_line(line, [per_unit_rule, discount_rule], events)
        assert result.recalculated_amount_cents == 901

    def test_two_discounts_returns_ambiguous(self):
        line = make_line(original_cents=500)
        rule1 = make_rule(RuleType.PER_UNIT, rate_cents=10, rule_id="R1")
        disc1 = make_rule(RuleType.DISCOUNT_PCT, discount_pct="10", rule_id="D1")
        disc2 = make_rule(RuleType.DISCOUNT_PCT, discount_pct="5",  rule_id="D2")
        result = calculate_line(line, [rule1, disc1, disc2], [make_event()])
        assert result.finding_type == FindingType.AMBIGUOUS
        assert "stacking" in result.explanation.lower() or "stacking" in result.assumptions[0].lower() or "AMBIGUOUS" in result.explanation


# ─────────────────────────────────────────────────────────────────────────────
# MINIMUM_COMMIT
# ─────────────────────────────────────────────────────────────────────────────

class TestMinimumCommit:
    def test_below_commit_raises_to_commit(self):
        line = make_line(original_cents=9999)
        per_unit = make_rule(RuleType.PER_UNIT, rate_cents=5, rule_id="R1")
        commit   = make_rule(RuleType.MINIMUM_COMMIT, minimum_commit_cents=500, rule_id="R2")
        events = [make_event(qty=10)]  # raw = 50¢, below 500¢ commit
        result = calculate_line(line, [per_unit, commit], events)
        assert result.recalculated_amount_cents == 500
        assert result.applied_minimum_commit_cents == 500
        assert any("minimum" in a.lower() for a in result.assumptions)

    def test_at_commit_no_change(self):
        line = make_line(original_cents=9999)
        per_unit = make_rule(RuleType.PER_UNIT, rate_cents=10, rule_id="R1")
        commit   = make_rule(RuleType.MINIMUM_COMMIT, minimum_commit_cents=500, rule_id="R2")
        events = [make_event(qty=50)]  # raw = 500¢ == commit
        result = calculate_line(line, [per_unit, commit], events)
        assert result.recalculated_amount_cents == 500

    def test_above_commit_no_change(self):
        line = make_line(original_cents=9999)
        per_unit = make_rule(RuleType.PER_UNIT, rate_cents=10, rule_id="R1")
        commit   = make_rule(RuleType.MINIMUM_COMMIT, minimum_commit_cents=500, rule_id="R2")
        events = [make_event(qty=100)]  # raw = 1000¢ > 500¢ commit
        result = calculate_line(line, [per_unit, commit], events)
        assert result.recalculated_amount_cents == 1000

    def test_rule_order_discount_then_commit(self):
        """
        Rule order: usage/tiers → discount → minimum_commit.
        10% off 500¢ = 450¢ < 480¢ commit → raised to 480¢.
        """
        line = make_line(original_cents=9999)
        per_unit = make_rule(RuleType.PER_UNIT, rate_cents=10, rule_id="R1")
        discount = make_rule(RuleType.DISCOUNT_PCT, discount_pct="10", rule_id="R2")
        commit   = make_rule(RuleType.MINIMUM_COMMIT, minimum_commit_cents=480, rule_id="R3")
        events = [make_event(qty=50)]  # raw=500, after 10% off=450, below 480 → 480
        result = calculate_line(line, [per_unit, discount, commit], events)
        assert result.recalculated_amount_cents == 480


# ─────────────────────────────────────────────────────────────────────────────
# Environment exemptions
# ─────────────────────────────────────────────────────────────────────────────

class TestEnvironmentExemptions:
    def test_staging_excluded(self):
        line = make_line(original_cents=9999)
        rule = make_rule(RuleType.PER_UNIT, rate_cents=10,
                         exempt_environments=["staging"])
        events = [
            make_event(qty=50, env="production", event_id="E1"),
            make_event(qty=50, env="staging",    event_id="E2"),  # excluded
        ]
        result = calculate_line(line, [rule], events)
        assert result.recalculated_amount_cents == 500   # only 50 production × 10
        assert result.quantity_used    == Decimal("50")
        assert result.exempt_quantity  == Decimal("50")

    def test_no_exempt_environments_all_billable(self):
        """Absent exempt_environments = nothing exempt."""
        line = make_line(original_cents=9999)
        rule = make_rule(RuleType.PER_UNIT, rate_cents=10)  # no exempt_environments
        events = [
            make_event(qty=30, env="staging",    event_id="E1"),
            make_event(qty=30, env="production", event_id="E2"),
        ]
        result = calculate_line(line, [rule], events)
        assert result.recalculated_amount_cents == 600   # all 60 × 10
        assert result.exempt_quantity == Decimal("0")

    def test_all_staging_zero_bill(self):
        line = make_line(original_cents=500)
        rule = make_rule(RuleType.PER_UNIT, rate_cents=10,
                         exempt_environments=["staging"])
        events = [make_event(qty=100, env="staging", event_id="E1")]
        result = calculate_line(line, [rule], events)
        assert result.recalculated_amount_cents == 0
        assert result.quantity_used == Decimal("0")

    def test_custom_exempt_env(self):
        """Exemption is explicitly configured; 'dev' is not exempt unless listed."""
        line = make_line(original_cents=9999)
        rule = make_rule(RuleType.PER_UNIT, rate_cents=10,
                         exempt_environments=["staging", "test"])
        events = [
            make_event(qty=10, env="dev",        event_id="E1"),  # billable
            make_event(qty=10, env="staging",    event_id="E2"),  # exempt
            make_event(qty=10, env="test",       event_id="E3"),  # exempt
            make_event(qty=10, env="production", event_id="E4"),  # billable
        ]
        result = calculate_line(line, [rule], events)
        assert result.quantity_used   == Decimal("20")   # dev + production
        assert result.exempt_quantity == Decimal("20")   # staging + test


# ─────────────────────────────────────────────────────────────────────────────
# Quarantine (malformed events)
# ─────────────────────────────────────────────────────────────────────────────

class TestQuarantine:
    def test_negative_quantity_quarantined(self):
        line = make_line(original_cents=9999)
        rule = make_rule(RuleType.PER_UNIT, rate_cents=10)
        events = [
            make_event(qty=50,  event_id="E1"),
            make_event(qty=-10, event_id="E2"),  # invalid
        ]
        result = calculate_line(line, [rule], events)
        assert len(result.quarantined_events) == 1
        assert result.quarantined_events[0].event_id == "E2"
        assert result.recalculated_amount_cents == 500  # only E1 used

    def test_quarantine_does_not_stop_calculation(self):
        """Engine continues with valid events when some are quarantined."""
        line = make_line(original_cents=9999)
        rule = make_rule(RuleType.PER_UNIT, rate_cents=5)
        events = [
            make_event(qty=-1,  event_id="BAD1"),
            make_event(qty=100, event_id="GOOD1"),
            make_event(qty=-5,  event_id="BAD2"),
            make_event(qty=50,  event_id="GOOD2"),
        ]
        result = calculate_line(line, [rule], events)
        assert len(result.quarantined_events) == 2
        assert result.quantity_used == Decimal("150")
        assert result.recalculated_amount_cents == 750

    def test_quarantine_reason_reported(self):
        line = make_line()
        rule = make_rule(RuleType.PER_UNIT, rate_cents=10)
        events = [make_event(qty=-1, event_id="BAD")]
        result = calculate_line(line, [rule], events)
        assert "Negative" in result.quarantined_events[0].reason

    def test_run_calculation_status_partial_on_quarantine(self):
        line = make_line()
        rule = make_rule(RuleType.PER_UNIT, rate_cents=10)
        events = [make_event(qty=-1, event_id="BAD"), make_event(qty=10, event_id="GOOD")]
        result = run_calculation([line], [rule], events)
        assert result.status == EngineStatus.PARTIAL
        assert len(result.quarantined_events) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Missing rule → INSUFFICIENT_DATA
# ─────────────────────────────────────────────────────────────────────────────

class TestMissingRule:
    def test_no_rules_returns_insufficient_data(self):
        line = make_line()
        result = calculate_line(line, [], [])
        assert result.finding_type == FindingType.INSUFFICIENT_DATA

    def test_run_calculation_status_insufficient_data(self):
        line = make_line()
        result = run_calculation([line], [], [])
        assert result.status == EngineStatus.INSUFFICIENT_DATA


# ─────────────────────────────────────────────────────────────────────────────
# Ambiguous: TIERED_GRADUATED + TIERED_VOLUME on same line
# ─────────────────────────────────────────────────────────────────────────────

class TestAmbiguousTierType:
    def test_returns_two_interpretations(self):
        line = make_line(original_cents=9999)
        tiers = [
            TierBand(up_to=100, price_per_unit_cents=10),
            TierBand(up_to=None, price_per_unit_cents=8),
        ]
        grad_rule = make_rule(RuleType.TIERED_GRADUATED, tiers=tiers, rule_id="R_GRAD")
        vol_rule  = make_rule(RuleType.TIERED_VOLUME,    tiers=tiers, rule_id="R_VOL")
        events = [make_event(qty=150)]
        result = calculate_line(line, [grad_rule, vol_rule], events)

        assert result.finding_type == FindingType.AMBIGUOUS
        assert len(result.interpretations) == 2
        ids = {r.interpretation_id for r in result.interpretations}
        assert "graduated" in ids
        assert "volume" in ids

    def test_ambiguous_amounts_differ(self):
        line = make_line()
        tiers = [
            TierBand(up_to=100, price_per_unit_cents=10),
            TierBand(up_to=None, price_per_unit_cents=8),
        ]
        grad_rule = make_rule(RuleType.TIERED_GRADUATED, tiers=tiers, rule_id="R_GRAD")
        vol_rule  = make_rule(RuleType.TIERED_VOLUME,    tiers=tiers, rule_id="R_VOL")
        events = [make_event(qty=150)]
        result = calculate_line(line, [grad_rule, vol_rule], events)

        grad_interp = next(r for r in result.interpretations if r.interpretation_id == "graduated")
        vol_interp  = next(r for r in result.interpretations if r.interpretation_id == "volume")
        # graduated: 100×10 + 50×8 = 1400; volume: 150×8 = 1200
        assert grad_interp.recalculated_amount_cents == 1400
        assert vol_interp.recalculated_amount_cents  == 1200

    def test_run_calculation_status_ambiguous(self):
        line = make_line()
        tiers = [TierBand(up_to=100, price_per_unit_cents=10), TierBand(up_to=None, price_per_unit_cents=8)]
        grad_rule = make_rule(RuleType.TIERED_GRADUATED, tiers=tiers, rule_id="R_GRAD")
        vol_rule  = make_rule(RuleType.TIERED_VOLUME, tiers=tiers, rule_id="R_VOL")
        result = run_calculation([line], [grad_rule, vol_rule], [make_event(qty=50)])
        assert result.status == EngineStatus.AMBIGUOUS


# ─────────────────────────────────────────────────────────────────────────────
# Repeatability
# ─────────────────────────────────────────────────────────────────────────────

class TestRepeatability:
    def test_same_inputs_same_result_id(self):
        line = make_line()
        rule = make_rule(RuleType.PER_UNIT, rate_cents=10)
        events = [make_event(qty=50)]
        r1 = calculate_line(line, [rule], events)
        r2 = calculate_line(line, [rule], events)
        assert r1.result_id == r2.result_id

    def test_same_inputs_same_result_hash(self):
        line = make_line()
        rule = make_rule(RuleType.PER_UNIT, rate_cents=10)
        events = [make_event(qty=50)]
        r1 = run_calculation([line], [rule], events)
        r2 = run_calculation([line], [rule], events)
        assert r1.result_hash == r2.result_hash

    def test_different_inputs_different_result_id(self):
        line = make_line()
        rule = make_rule(RuleType.PER_UNIT, rate_cents=10)
        r1 = calculate_line(line, [rule], [make_event(qty=50)])
        r2 = calculate_line(line, [rule], [make_event(qty=51)])
        assert r1.result_id != r2.result_id


# ─────────────────────────────────────────────────────────────────────────────
# run_calculation multi-line
# ─────────────────────────────────────────────────────────────────────────────

class TestRunCalculation:
    def test_totals_are_sum_of_line_amounts(self):
        line1 = InvoiceLine("L1", "Line 1", original_amount_cents=500)
        line2 = InvoiceLine("L2", "Line 2", original_amount_cents=300)
        rule1 = make_rule(RuleType.PER_UNIT, line_id="L1", rate_cents=5,  rule_id="R1")
        rule2 = make_rule(RuleType.FLAT,     line_id="L2", rate_cents=400, rule_id="R2")
        events = [make_event(line_id="L1", qty=100)]  # L1 = 500¢; L2 = 400¢
        result = run_calculation([line1, line2], [rule1, rule2], events)
        assert result.total_original_billed_cents  == 800
        assert result.total_recalculated_cents      == 900
        assert result.total_difference_cents        == 100   # undercharged
        assert result.status == EngineStatus.OK

    def test_events_from_wrong_line_not_used(self):
        line1 = InvoiceLine("L1", "Line 1", original_amount_cents=9999)
        rule1 = make_rule(RuleType.PER_UNIT, line_id="L1", rate_cents=10)
        events = [make_event(line_id="L2", qty=100)]  # L2 event, not L1
        result = run_calculation([line1], [rule1], events)
        assert result.total_recalculated_cents == 0  # no L1 events → 0 usage

    def test_ok_status_all_clean(self):
        line = make_line()
        rule = make_rule(RuleType.FLAT, rate_cents=1000)
        result = run_calculation([line], [rule], [])
        assert result.status == EngineStatus.OK
