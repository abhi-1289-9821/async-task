"""
billing_engine.py
=================
Deterministic billing recalculation engine.

ISOLATION CONTRACT:
  - This module imports ONLY Python stdlib: decimal, dataclasses, enum, hashlib, typing.
  - Zero imports from app/, LangGraph, SQLAlchemy, FastAPI, or any HTTP library.
  - Every function is a pure transformation: same inputs → identical outputs.
  - All money arithmetic uses Decimal. Floats are NEVER used.

ROUNDING POLICY:
  - Intermediate calculations stay in Decimal with full precision.
  - ROUND_HALF_UP is applied ONCE per invoice line at the line-item boundary
    (the single call to _round_cents() at the end of each line calculation).
  - The invoice total is the integer sum of already-rounded line amounts.
  - This is documented and tested in test_billing_engine.py.

RULE EVALUATION ORDER (per invoice line):
  1. Compute raw amount from rule type (FLAT / PER_UNIT / TIERED_GRADUATED /
     TIERED_VOLUME / INCLUDED_UNITS).
  2. Apply DISCOUNT_PCT if present (one discount per line; two → UNRESOLVED).
  3. Apply MINIMUM_COMMIT if present (raises amount to minimum if below it).
  4. Round to integer cents (ROUND_HALF_UP).

ENVIRONMENT EXEMPTION:
  - Each ContractRule carries an optional `exempt_environments` list.
  - Usage events whose `environment` field appears in that list are excluded
    from quantity totals BEFORE any rule is applied.
  - There is NO implicit default. Absent = nothing exempt.

TIERED_VOLUME BOUNDARY:
  - Tiers use an inclusive `up_to` value.
  - A quantity equal to `up_to` belongs to THAT tier (not the next one).
  - Example: tier1 up_to=100 price=10, tier2 up_to=200 price=8.
    quantity=100 → tier1 price=10. quantity=101 → tier2 price=8.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# Enumerations
# ─────────────────────────────────────────────────────────────────────────────

class RuleType(str, Enum):
    FLAT = "FLAT"
    PER_UNIT = "PER_UNIT"
    TIERED_GRADUATED = "TIERED_GRADUATED"
    TIERED_VOLUME = "TIERED_VOLUME"
    INCLUDED_UNITS = "INCLUDED_UNITS"
    DISCOUNT_PCT = "DISCOUNT_PCT"
    MINIMUM_COMMIT = "MINIMUM_COMMIT"


class EngineStatus(str, Enum):
    OK = "OK"
    AMBIGUOUS = "AMBIGUOUS"          # Multiple valid interpretations; flag for human review
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"  # Required input is missing
    PARTIAL = "PARTIAL"              # Some events quarantined; calculation continued


class FindingType(str, Enum):
    """Outcome of comparing original billed vs recalculated for one line."""
    CONFIRMED_CALCULATION_DISCREPANCY = "CONFIRMED_CALCULATION_DISCREPANCY"
    NO_DISCREPANCY = "NO_DISCREPANCY"
    AMBIGUOUS = "AMBIGUOUS"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


# ─────────────────────────────────────────────────────────────────────────────
# Input data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TierBand:
    """
    A single tier band for TIERED_GRADUATED or TIERED_VOLUME rules.
    up_to: inclusive upper bound in usage units. None means "unlimited" (last tier).
    price_per_unit_cents: price for units in this band.
    """
    price_per_unit_cents: int         # Must be >= 0
    up_to: int | None = None          # None = unlimited (must be the last tier)


@dataclass
class ContractRule:
    """
    One pricing rule attached to one invoice line.

    Fields:
      rule_id:               stable string ID (used in result citations)
      line_id:               which invoice line this rule applies to
      rule_type:             RuleType enum
      rate_cents:            price per unit (PER_UNIT) or flat amount (FLAT) or
                             included-unit overage rate (INCLUDED_UNITS)
      tiers:                 list of TierBand for TIERED_* rules
      discount_pct:          percentage for DISCOUNT_PCT (e.g. Decimal("10") = 10%)
      minimum_commit_cents:  floor for MINIMUM_COMMIT
      included_units:        free units for INCLUDED_UNITS
      overage_rate_cents:    overage price for INCLUDED_UNITS (overrides rate_cents if set)
      exempt_environments:   environments whose usage is excluded from totals.
                             Absent / None / empty = nothing exempt. NO implicit default.
    """
    rule_id: str
    line_id: str
    rule_type: RuleType
    rate_cents: int = 0
    tiers: list[TierBand] = field(default_factory=list)
    discount_pct: Decimal | None = Decimal("0")
    minimum_commit_cents: int = 0
    included_units: int = 0
    overage_rate_cents: int | None = None
    exempt_environments: list[str] = field(default_factory=list)


@dataclass
class UsageEvent:
    """
    One usage measurement for a case.

    Fields:
      event_id:    stable string ID
      line_id:     which invoice line this event belongs to
      quantity:    number of units used (must be >= 0 for valid events)
      environment: e.g. "production", "staging". Used for exemption checks.
      raw:         original dict, preserved for audit / quarantine reporting
    """
    event_id: str
    line_id: str
    quantity: Decimal
    environment: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class InvoiceLine:
    """
    One line on the original invoice — what the customer was actually billed.

    Fields:
      line_id:               stable string ID
      description:           human-readable (e.g. "API calls - March 2026")
      original_amount_cents: what the customer was charged (integer cents)
    """
    line_id: str
    description: str
    original_amount_cents: int


# ─────────────────────────────────────────────────────────────────────────────
# Output data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class QuarantinedEvent:
    """A usage event that failed validation and was excluded from calculation."""
    event_id: str
    reason: str
    raw: dict[str, Any]


@dataclass
class InterpretationResult:
    """
    One interpretation of an ambiguous rule.
    Returned in pairs/lists when a rule has multiple valid readings.
    """
    interpretation_id: str        # e.g. "graduated" or "volume"
    recalculated_amount_cents: int
    assumptions: list[str]        # Plain-language list of what this reading assumes
    rule_id: str
    line_id: str


@dataclass
class LineCalculationResult:
    """
    The engine's output for a single invoice line.

    result_id is deterministic: SHA-256 of (line_id + rule_id + inputs summary).
    This means the same inputs always produce the same result_id, making it
    safe to use as a citation reference in findings.
    """
    result_id: str
    line_id: str
    rule_id: str
    original_amount_cents: int
    recalculated_amount_cents: int
    difference_cents: int          # recalculated - original (negative = overcharge)
    finding_type: FindingType
    quantity_used: Decimal         # After exemptions applied
    exempt_quantity: Decimal       # How many units were excluded
    quarantined_events: list[QuarantinedEvent]
    applied_discount_pct: Decimal
    applied_minimum_commit_cents: int
    interpretations: list[InterpretationResult]  # Non-empty only for AMBIGUOUS
    assumptions: list[str]         # Assumptions this calculation relied on
    explanation: str               # Human-readable single-sentence explanation


@dataclass
class EngineResult:
    """
    Top-level result returned by run_calculation().

    Aggregates all line results into an invoice-level summary.
    All amounts in integer cents.
    """
    status: EngineStatus
    line_results: list[LineCalculationResult]
    total_original_billed_cents: int
    total_recalculated_cents: int
    total_difference_cents: int     # recalculated - original
    quarantined_events: list[QuarantinedEvent]
    result_hash: str                # SHA-256 of all inputs, for reproducibility verification
    status_reason: str = ""         # Set when status != OK


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _round_cents(value: Decimal) -> int:
    """
    Apply the project rounding policy: ROUND_HALF_UP to integer cents.
    Called ONCE at the line-item boundary after all arithmetic is done.
    Do NOT call this on intermediate values.
    """
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _validate_event(event: UsageEvent) -> str | None:
    """
    Validate a single usage event.
    Returns None if valid, or a human-readable reason string if invalid.
    """
    if event.quantity.is_nan() or event.quantity.is_infinite():
        return f"Invalid non-finite quantity {event.quantity}"
    if event.quantity < Decimal("0"):
        return f"Negative quantity {event.quantity}"
    if not event.line_id:
        return "Missing line_id"
    if not event.event_id:
        return "Missing event_id"
    if not isinstance(event.environment, str):
        return "environment must be a string"
    return None


def _partition_events(
    events: list[UsageEvent],
    line_id: str,
    exempt_environments: list[str],
) -> tuple[list[UsageEvent], list[UsageEvent], list[QuarantinedEvent]]:
    """
    Split events for a given line into:
      - valid_billable:  pass validation, environment not exempt
      - valid_exempt:    pass validation, environment IS exempt
      - quarantined:     fail validation

    Malformed events are quarantined; calculation continues with the rest.
    """
    billable: list[UsageEvent] = []
    exempt: list[UsageEvent] = []
    quarantined: list[QuarantinedEvent] = []

    for ev in events:
        reason = _validate_event(ev)
        if reason:
            quarantined.append(QuarantinedEvent(
                event_id=ev.event_id,
                reason=reason,
                raw=ev.raw,
            ))
            continue
        if ev.line_id != line_id:
            continue
        if ev.environment in exempt_environments:
            exempt.append(ev)
        else:
            billable.append(ev)

    return billable, exempt, quarantined


def _serialize_rule(r: ContractRule) -> dict[str, Any]:
    return {
        "rule_id": r.rule_id,
        "line_id": r.line_id,
        "rule_type": r.rule_type.value,
        "rate_cents": int(r.rate_cents),
        "tiers": [
            {"up_to": t.up_to, "price_per_unit_cents": int(t.price_per_unit_cents)}
            for t in (r.tiers or [])
        ],
        "discount_pct": str(r.discount_pct) if r.discount_pct is not None else "0",
        "minimum_commit_cents": int(r.minimum_commit_cents),
        "included_units": str(r.included_units),
        "overage_rate_cents": int(r.overage_rate_cents) if r.overage_rate_cents is not None else None,
        "exempt_environments": sorted(r.exempt_environments or []),
    }


def _compute_result_id(
    line_id: str,
    rule_id: str,
    quantity: Decimal,
    rule_type: RuleType,
    rule: ContractRule | None = None,
    rules: list[ContractRule] | None = None,
    original_amount_cents: int = 0,
    applied_discount_pct: Decimal = Decimal("0"),
    applied_minimum_commit_cents: int = 0,
) -> str:
    """
    Deterministic result ID: SHA-256 of all pricing inputs.
    Covers rates, tiers, discounts, commitments, original amount, and quantities.
    Same inputs always produce the same ID — safe to cite in findings.
    """
    payload_dict: dict[str, Any] = {
        "line_id": line_id,
        "rule_id": rule_id,
        "quantity": str(quantity),
        "rule_type": rule_type.value,
        "original_amount_cents": original_amount_cents,
        "applied_discount_pct": str(applied_discount_pct),
        "applied_minimum_commit_cents": applied_minimum_commit_cents,
    }
    all_rules = list(rules) if rules else ([rule] if rule else [])
    if all_rules:
        payload_dict["rules"] = sorted([_serialize_rule(r) for r in all_rules], key=lambda x: x["rule_id"])
    payload = json.dumps(payload_dict, sort_keys=True)
    return "res_" + hashlib.sha256(payload.encode()).hexdigest()[:16]


def _compute_input_hash(
    lines: list[InvoiceLine],
    rules: list[ContractRule],
    events: list[UsageEvent],
) -> str:
    """
    SHA-256 of the full input set. Used as EngineResult.result_hash.
    Lets the caller verify that a cached result came from the same inputs.
    """
    payload = json.dumps({
        "lines": sorted([{"id": l.line_id, "desc": l.description, "orig": l.original_amount_cents} for l in lines], key=lambda x: x["id"]),
        "rules": sorted([_serialize_rule(r) for r in rules], key=lambda x: x["rule_id"]),
        "events": sorted([{"id": e.event_id, "line_id": e.line_id, "qty": str(e.quantity), "env": e.environment}
                          for e in events], key=lambda x: x["id"]),
    }, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# Rule computation functions
# Each returns a raw Decimal amount (NOT yet rounded).
# ─────────────────────────────────────────────────────────────────────────────

def _apply_flat(rule: ContractRule) -> Decimal:
    """FLAT: fixed amount regardless of usage. Returns rate_cents as Decimal."""
    return Decimal(rule.rate_cents)


def _apply_per_unit(rule: ContractRule, quantity: Decimal) -> Decimal:
    """PER_UNIT: quantity × unit_price_cents."""
    return quantity * Decimal(rule.rate_cents)


def _apply_tiered_graduated(rule: ContractRule, quantity: Decimal) -> tuple[Decimal, bool]:
    """
    TIERED_GRADUATED: each tier's rate applies only to units within that tier's band.

    Example: tiers = [(up_to=100, price=10), (up_to=200, price=8), (up_to=None, price=6)]
      quantity=150 → 100×10 + 50×8 = 1400
      quantity=250 → 100×10 + 100×8 + 50×6 = 2100
    Returns (raw_amount, uncovered_bool).
    """
    total = Decimal("0")
    remaining = quantity
    prev_boundary = Decimal("0")

    for tier in rule.tiers:
        if remaining <= Decimal("0"):
            break
        if tier.up_to is not None:
            band_size = Decimal(tier.up_to) - prev_boundary
            units_in_band = min(remaining, band_size)
            prev_boundary = Decimal(tier.up_to)
        else:
            units_in_band = remaining  # last tier catches all remainder

        total += units_in_band * Decimal(tier.price_per_unit_cents)
        remaining -= units_in_band

    uncovered = (remaining > Decimal("0"))
    return total, uncovered


def _apply_tiered_volume(rule: ContractRule, quantity: Decimal) -> tuple[Decimal, bool]:
    """
    TIERED_VOLUME: ALL units are priced at the rate of the tier the quantity falls into.
    Tier selection uses inclusive up_to: quantity <= up_to → use this tier's price.

    Example: tiers = [(up_to=100, price=10), (up_to=200, price=8), (up_to=None, price=6)]
      quantity=100 → 100×10 = 1000  (boundary belongs to tier1)
      quantity=101 → 101×8  = 808   (into tier2)
    Returns (raw_amount, uncovered_bool).
    """
    if quantity == Decimal("0"):
        return Decimal("0"), False
    for tier in rule.tiers:
        if tier.up_to is None or quantity <= Decimal(tier.up_to):
            return quantity * Decimal(tier.price_per_unit_cents), False
    # Usage exceeded highest bounded tier without catch-all
    return Decimal("0"), True


def _apply_included_units(rule: ContractRule, quantity: Decimal) -> Decimal:
    """
    INCLUDED_UNITS: first N units are free, overages billed at overage_rate_cents
    (falls back to rate_cents if overage_rate_cents not set).

    bill = max(0, quantity - included_units) × overage_rate
    """
    overage_rate = Decimal(
        rule.overage_rate_cents if rule.overage_rate_cents is not None else rule.rate_cents
    )
    overage_qty = max(Decimal("0"), quantity - Decimal(rule.included_units))
    return overage_qty * overage_rate


# ─────────────────────────────────────────────────────────────────────────────
# Main calculation entry point
# ─────────────────────────────────────────────────────────────────────────────

def calculate_line(
    line: InvoiceLine,
    rules_for_line: list[ContractRule],
    events: list[UsageEvent],
) -> LineCalculationResult:
    """
    Calculate the correct charge for a single invoice line.

    Rules:
      - Exactly one primary rule (FLAT/PER_UNIT/TIERED_*/INCLUDED_UNITS) expected.
        If missing → INSUFFICIENT_DATA.
        If multiple competing primary rules present → AMBIGUOUS.
      - Exactly one DISCOUNT_PCT at most. Two on one line → AMBIGUOUS.
      - At most one MINIMUM_COMMIT. Two on one line → AMBIGUOUS.
      - TIERED_GRADUATED and TIERED_VOLUME on the same line → AMBIGUOUS
        (returns two InterpretationResult objects with 0 difference_cents).
    """
    quarantined_all: list[QuarantinedEvent] = []
    assumptions: list[str] = []

    # ── 1. Identify rule types present ───────────────────────────────────────
    primary_rules = [r for r in rules_for_line if r.rule_type not in (
        RuleType.DISCOUNT_PCT, RuleType.MINIMUM_COMMIT
    )]
    discount_rules = [r for r in rules_for_line if r.rule_type == RuleType.DISCOUNT_PCT]
    commit_rules   = [r for r in rules_for_line if r.rule_type == RuleType.MINIMUM_COMMIT]

    # ── 2. Guard: missing primary rule ───────────────────────────────────────
    if not primary_rules:
        return LineCalculationResult(
            result_id=_compute_result_id(line.line_id, "none", Decimal("0"), RuleType.FLAT),
            line_id=line.line_id,
            rule_id="none",
            original_amount_cents=line.original_amount_cents,
            recalculated_amount_cents=0,
            difference_cents=0,
            finding_type=FindingType.INSUFFICIENT_DATA,
            quantity_used=Decimal("0"),
            exempt_quantity=Decimal("0"),
            quarantined_events=[],
            applied_discount_pct=Decimal("0"),
            applied_minimum_commit_cents=0,
            interpretations=[],
            assumptions=["No primary pricing rule found for this line"],
            explanation="Cannot recalculate: no primary pricing rule found.",
        )

    # ── 3. Guard: two discount rules → AMBIGUOUS ─────────────────────────────
    if len(discount_rules) > 1:
        return _make_ambiguous_result(
            line=line,
            rule_id=discount_rules[0].rule_id,
            reason="Multiple DISCOUNT_PCT rules on one line; stacking semantics undefined.",
            assumptions=["Each discount rule found: " + ", ".join(r.rule_id for r in discount_rules)],
        )

    # ── 4. Guard: two commit rules → AMBIGUOUS ────────────────────────────────
    if len(commit_rules) > 1:
        return _make_ambiguous_result(
            line=line,
            rule_id=commit_rules[0].rule_id,
            reason="Multiple MINIMUM_COMMIT rules on one line; which applies is undefined.",
            assumptions=[],
        )

    # Engine-level input validation for discount rules
    if discount_rules:
        d_pct = discount_rules[0].discount_pct
        if d_pct is None or not isinstance(d_pct, Decimal):
            return _make_insufficient_data_result(
                line, discount_rules[0].rule_id,
                "DISCOUNT_PCT rule is missing discount percentage",
                quarantined_all,
            )
        if d_pct.is_nan() or d_pct.is_infinite() or d_pct < Decimal("0") or d_pct > Decimal("100"):
            return _make_insufficient_data_result(
                line, discount_rules[0].rule_id,
                f"Invalid discount percentage {d_pct}% (must be finite between 0 and 100)",
                quarantined_all,
            )

    # Engine-level input validation for tiered rules
    for r in primary_rules:
        if r.rule_type in (RuleType.TIERED_GRADUATED, RuleType.TIERED_VOLUME):
            if not r.tiers:
                return _make_insufficient_data_result(
                    line, r.rule_id, "Tiered rule has empty or missing tiers", quarantined_all
                )
            prev_bound = Decimal("0")
            for t in r.tiers:
                if t.price_per_unit_cents < 0:
                    return _make_insufficient_data_result(
                        line, r.rule_id, f"Negative tier rate {t.price_per_unit_cents}", quarantined_all
                    )
                if t.up_to is not None:
                    bound = Decimal(t.up_to)
                    if bound.is_nan() or bound.is_infinite() or bound <= prev_bound:
                        return _make_insufficient_data_result(
                            line, r.rule_id, f"Tiers must have strictly increasing finite upper bounds ({bound} <= {prev_bound})", quarantined_all
                        )
                    prev_bound = bound

    # ── 5. Guard: multiple primary rules ──────────────────────────────────────
    has_graduated = any(r.rule_type == RuleType.TIERED_GRADUATED for r in primary_rules)
    has_volume    = any(r.rule_type == RuleType.TIERED_VOLUME    for r in primary_rules)
    if len(primary_rules) > 1 and not (has_graduated and has_volume and len(primary_rules) == 2):
        return _make_ambiguous_result(
            line=line,
            rule_id=primary_rules[0].rule_id,
            reason="Multiple conflicting primary pricing rules on one line; rule priority undefined.",
            assumptions=[f"Primary rules found: {', '.join(r.rule_id for r in primary_rules)}"],
        )

    # ── 5a. Guard: TIERED_GRADUATED + TIERED_VOLUME on same line → AMBIGUOUS ──
    if has_graduated and has_volume:
        # We have two valid interpretations; compute both and return as AMBIGUOUS
        grad_rule = next(r for r in primary_rules if r.rule_type == RuleType.TIERED_GRADUATED)
        vol_rule  = next(r for r in primary_rules if r.rule_type == RuleType.TIERED_VOLUME)

        billable, exempt_evs, q = _partition_events(
            events, line.line_id, grad_rule.exempt_environments
        )
        quarantined_all.extend(q)
        if not billable and not exempt_evs:
            reason = (
                "All usage events were quarantined due to validation errors; insufficient valid data to recalculate."
                if quarantined_all
                else "Metered pricing rule requires usage events, but no events were found for this line."
            )
            return _make_insufficient_data_result(
                line=line,
                rule_id=grad_rule.rule_id,
                reason=reason,
                quarantined_events=quarantined_all,
            )
        quantity = sum((e.quantity for e in billable), Decimal("0"))
        exempt_qty = sum((e.quantity for e in exempt_evs), Decimal("0"))

        grad_raw, grad_uncovered = _apply_tiered_graduated(grad_rule, quantity)
        vol_raw, vol_uncovered   = _apply_tiered_volume(vol_rule, quantity)

        if grad_uncovered or vol_uncovered:
            return LineCalculationResult(
                result_id=_compute_result_id(
                    line.line_id, grad_rule.rule_id, quantity, RuleType.TIERED_GRADUATED,
                    rules=rules_for_line, original_amount_cents=line.original_amount_cents
                ),
                line_id=line.line_id,
                rule_id=grad_rule.rule_id,
                original_amount_cents=line.original_amount_cents,
                recalculated_amount_cents=0,
                difference_cents=0,
                finding_type=FindingType.INSUFFICIENT_DATA,
                quantity_used=quantity,
                exempt_quantity=exempt_qty,
                quarantined_events=quarantined_all,
                applied_discount_pct=Decimal("0"),
                applied_minimum_commit_cents=0,
                interpretations=[],
                assumptions=["Usage exceeds tier boundaries without unbounded catch-all in ambiguous rules."],
                explanation=f"Cannot recalculate: usage of {quantity} units exceeds bounded tier brackets.",
            )

        applied_disc = discount_rules[0].discount_pct if discount_rules else Decimal("0")
        applied_commit = commit_rules[0].minimum_commit_cents if commit_rules else 0

        if discount_rules:
            grad_raw = grad_raw - (grad_raw * (applied_disc / Decimal("100")))
            vol_raw  = vol_raw - (vol_raw * (applied_disc / Decimal("100")))
        if commit_rules:
            if grad_raw < Decimal(applied_commit):
                grad_raw = Decimal(applied_commit)
            if vol_raw < Decimal(applied_commit):
                vol_raw = Decimal(applied_commit)

        grad_amt = _round_cents(grad_raw)
        vol_amt  = _round_cents(vol_raw)

        return LineCalculationResult(
            result_id=_compute_result_id(
                line.line_id, grad_rule.rule_id, quantity, RuleType.TIERED_GRADUATED,
                rules=rules_for_line, original_amount_cents=line.original_amount_cents,
                applied_discount_pct=applied_disc, applied_minimum_commit_cents=applied_commit
            ),
            line_id=line.line_id,
            rule_id=grad_rule.rule_id,
            original_amount_cents=line.original_amount_cents,
            recalculated_amount_cents=0,
            difference_cents=0,
            finding_type=FindingType.AMBIGUOUS,
            quantity_used=quantity,
            exempt_quantity=exempt_qty,
            quarantined_events=quarantined_all,
            applied_discount_pct=applied_disc,
            applied_minimum_commit_cents=applied_commit,
            interpretations=[
                InterpretationResult(
                    interpretation_id="graduated",
                    recalculated_amount_cents=grad_amt,
                    assumptions=["Contract clause read as TIERED_GRADUATED: each tier's rate applies only to units within that band."],
                    rule_id=grad_rule.rule_id,
                    line_id=line.line_id,
                ),
                InterpretationResult(
                    interpretation_id="volume",
                    recalculated_amount_cents=vol_amt,
                    assumptions=["Contract clause read as TIERED_VOLUME: all units priced at the rate of the tier the total quantity falls into."],
                    rule_id=vol_rule.rule_id,
                    line_id=line.line_id,
                ),
            ],
            assumptions=["Tier type is ambiguous; human review required to select graduated or volume interpretation."],
            explanation=f"Ambiguous tier type. Graduated interpretation: {grad_amt}¢. Volume interpretation: {vol_amt}¢.",
        )

    # ── 6. Single primary rule — normal path ──────────────────────────────────
    primary = primary_rules[0]
    discount_rule = discount_rules[0] if discount_rules else None
    commit_rule   = commit_rules[0]   if commit_rules   else None

    billable, exempt_evs, q = _partition_events(
        events, line.line_id, primary.exempt_environments
    )
    quarantined_all.extend(q)

    # Metered pricing rules require valid usage evidence
    metered_rule_types = {
        RuleType.PER_UNIT,
        RuleType.TIERED_GRADUATED,
        RuleType.TIERED_VOLUME,
        RuleType.INCLUDED_UNITS,
    }
    if primary.rule_type in metered_rule_types and not billable and not exempt_evs:
        reason = (
            "All usage events were quarantined due to validation errors; insufficient valid data to recalculate."
            if quarantined_all
            else "Metered pricing rule requires usage events, but no events were found for this line."
        )
        return _make_insufficient_data_result(
            line=line,
            rule_id=primary.rule_id,
            reason=reason,
            quarantined_events=quarantined_all,
        )

    quantity    = sum((e.quantity for e in billable), Decimal("0"))
    exempt_qty  = sum((e.quantity for e in exempt_evs), Decimal("0"))

    if exempt_qty > Decimal("0"):
        assumptions.append(
            f"{exempt_qty} units excluded because environment is in exempt list "
            f"{primary.exempt_environments!r}."
        )

    # ── 6a. Compute raw amount by rule type ──────────────────────────────────
    if primary.rule_type == RuleType.FLAT:
        raw_amount = _apply_flat(primary)
        assumptions.append("FLAT rule: amount is fixed regardless of usage quantity.")
    elif primary.rule_type == RuleType.PER_UNIT:
        raw_amount = _apply_per_unit(primary, quantity)
    elif primary.rule_type == RuleType.TIERED_GRADUATED:
        raw_amount, uncovered = _apply_tiered_graduated(primary, quantity)
        if uncovered:
            return LineCalculationResult(
                result_id=_compute_result_id(line.line_id, primary.rule_id, quantity, primary.rule_type, rule=primary, original_amount_cents=line.original_amount_cents),
                line_id=line.line_id,
                rule_id=primary.rule_id,
                original_amount_cents=line.original_amount_cents,
                recalculated_amount_cents=0,
                difference_cents=0,
                finding_type=FindingType.INSUFFICIENT_DATA,
                quantity_used=quantity,
                exempt_quantity=exempt_qty,
                quarantined_events=quarantined_all,
                applied_discount_pct=Decimal("0"),
                applied_minimum_commit_cents=0,
                interpretations=[],
                assumptions=["Usage exceeds highest defined tier bracket without unbounded catch-all."],
                explanation=f"Cannot recalculate: usage of {quantity} units exceeds highest tier bracket.",
            )
        assumptions.append("TIERED_GRADUATED: each tier's rate applies only to units within that band.")
    elif primary.rule_type == RuleType.TIERED_VOLUME:
        raw_amount, uncovered = _apply_tiered_volume(primary, quantity)
        if uncovered:
            return LineCalculationResult(
                result_id=_compute_result_id(line.line_id, primary.rule_id, quantity, primary.rule_type, rule=primary, original_amount_cents=line.original_amount_cents),
                line_id=line.line_id,
                rule_id=primary.rule_id,
                original_amount_cents=line.original_amount_cents,
                recalculated_amount_cents=0,
                difference_cents=0,
                finding_type=FindingType.INSUFFICIENT_DATA,
                quantity_used=quantity,
                exempt_quantity=exempt_qty,
                quarantined_events=quarantined_all,
                applied_discount_pct=Decimal("0"),
                applied_minimum_commit_cents=0,
                interpretations=[],
                assumptions=["Usage exceeds highest defined tier bracket without unbounded catch-all."],
                explanation=f"Cannot recalculate: usage of {quantity} units exceeds highest tier bracket.",
            )
        assumptions.append("TIERED_VOLUME: all units priced at the rate of the tier the total quantity falls into.")
    elif primary.rule_type == RuleType.INCLUDED_UNITS:
        raw_amount = _apply_included_units(primary, quantity)
        assumptions.append(
            f"INCLUDED_UNITS: first {primary.included_units} units free; "
            f"overage at {primary.overage_rate_cents or primary.rate_cents}¢/unit."
        )
    else:
        # Should not happen if primary_rules filter is correct, but be safe
        return _make_ambiguous_result(line, primary.rule_id, f"Unhandled rule type {primary.rule_type}", [])

    # ── 6b. Apply discount (step 2 of rule order) ────────────────────────────
    applied_discount_pct = Decimal("0")
    if discount_rule and discount_rule.discount_pct is not None:
        applied_discount_pct = discount_rule.discount_pct
        discount_amount = raw_amount * (applied_discount_pct / Decimal("100"))
        raw_amount = raw_amount - discount_amount
        # Note: no rounding here — still Decimal; rounding happens at line boundary

    # ── 6c. Apply minimum commit (step 3 of rule order) ──────────────────────
    applied_commit = 0
    if commit_rule:
        applied_commit = commit_rule.minimum_commit_cents
        if raw_amount < Decimal(applied_commit):
            assumptions.append(
                f"MINIMUM_COMMIT applied: usage amount {raw_amount}¢ was below "
                f"the {applied_commit}¢ minimum; raised to minimum."
            )
            raw_amount = Decimal(applied_commit)

    # ── 6d. Round to integer cents at line boundary ──────────────────────────
    recalculated = _round_cents(raw_amount)
    difference   = recalculated - line.original_amount_cents

    # ── 6e. Classify finding type ────────────────────────────────────────────
    if difference != 0:
        finding_type = FindingType.CONFIRMED_CALCULATION_DISCREPANCY
    else:
        finding_type = FindingType.NO_DISCREPANCY

    # ── 6f. Build explanation ────────────────────────────────────────────────
    if difference < 0:
        explanation = (
            f"Customer was overcharged by {abs(difference)}¢. "
            f"Billed: {line.original_amount_cents}¢, correct: {recalculated}¢."
        )
    elif difference > 0:
        explanation = (
            f"Customer was undercharged by {difference}¢. "
            f"Billed: {line.original_amount_cents}¢, correct: {recalculated}¢."
        )
    else:
        explanation = f"Billing is correct at {recalculated}¢."

    return LineCalculationResult(
        result_id=_compute_result_id(
            line.line_id, primary.rule_id, quantity, primary.rule_type,
            rules=rules_for_line, original_amount_cents=line.original_amount_cents,
            applied_discount_pct=applied_discount_pct, applied_minimum_commit_cents=applied_commit,
        ),
        line_id=line.line_id,
        rule_id=primary.rule_id,
        original_amount_cents=line.original_amount_cents,
        recalculated_amount_cents=recalculated,
        difference_cents=difference,
        finding_type=finding_type,
        quantity_used=quantity,
        exempt_quantity=exempt_qty,
        quarantined_events=quarantined_all,
        applied_discount_pct=applied_discount_pct,
        applied_minimum_commit_cents=applied_commit,
        interpretations=[],
        assumptions=assumptions,
        explanation=explanation,
    )


def _make_ambiguous_result(
    line: InvoiceLine,
    rule_id: str,
    reason: str,
    assumptions: list[str],
) -> LineCalculationResult:
    """Helper: build a LineCalculationResult with AMBIGUOUS finding_type."""
    return LineCalculationResult(
        result_id=_compute_result_id(line.line_id, rule_id, Decimal("0"), RuleType.FLAT, original_amount_cents=line.original_amount_cents),
        line_id=line.line_id,
        rule_id=rule_id,
        original_amount_cents=line.original_amount_cents,
        recalculated_amount_cents=0,
        difference_cents=0,
        finding_type=FindingType.AMBIGUOUS,
        quantity_used=Decimal("0"),
        exempt_quantity=Decimal("0"),
        quarantined_events=[],
        applied_discount_pct=Decimal("0"),
        applied_minimum_commit_cents=0,
        interpretations=[],
        assumptions=assumptions,
        explanation=f"AMBIGUOUS: {reason}",
    )


def _make_insufficient_data_result(
    line: InvoiceLine,
    rule_id: str,
    reason: str,
    quarantined_events: list[QuarantinedEvent] | None = None,
) -> LineCalculationResult:
    """Helper: build a LineCalculationResult with INSUFFICIENT_DATA finding_type."""
    return LineCalculationResult(
        result_id=_compute_result_id(line.line_id, rule_id, Decimal("0"), RuleType.FLAT, original_amount_cents=line.original_amount_cents),
        line_id=line.line_id,
        rule_id=rule_id,
        original_amount_cents=line.original_amount_cents,
        recalculated_amount_cents=0,
        difference_cents=0,
        finding_type=FindingType.INSUFFICIENT_DATA,
        quantity_used=Decimal("0"),
        exempt_quantity=Decimal("0"),
        quarantined_events=quarantined_events or [],
        applied_discount_pct=Decimal("0"),
        applied_minimum_commit_cents=0,
        interpretations=[],
        assumptions=[reason],
        explanation=f"Cannot recalculate: {reason}",
    )


def run_calculation(
    lines: list[InvoiceLine],
    rules: list[ContractRule],
    events: list[UsageEvent],
) -> EngineResult:
    """
    Run the billing engine over all invoice lines.

    For each line:
      - Find rules where rule.line_id == line.line_id
      - Find events where event.line_id == line.line_id
      - Call calculate_line()

    If no rules exist for any line, that line gets INSUFFICIENT_DATA.
    Status is PARTIAL if any events were quarantined (calculation still completes).
    Status is AMBIGUOUS if any line is AMBIGUOUS (and no other errors).
    Status is INSUFFICIENT_DATA if any line lacks rules.
    Status is OK if all lines computed cleanly.

    The invoice total is the SUM of already-rounded line amounts.
    """
    line_results: list[LineCalculationResult] = []
    all_quarantined: list[QuarantinedEvent] = []

    valid_line_ids = {line.line_id for line in lines}
    seen_event_ids: set[str] = set()
    cleaned_events: list[UsageEvent] = []

    for ev in events:
        if ev.event_id in seen_event_ids:
            all_quarantined.append(QuarantinedEvent(
                event_id=ev.event_id,
                reason=f"Duplicate event_id '{ev.event_id}'",
                raw=ev.raw,
            ))
            continue
        seen_event_ids.add(ev.event_id)

        if not ev.line_id:
            all_quarantined.append(QuarantinedEvent(
                event_id=ev.event_id,
                reason="Missing line_id",
                raw=ev.raw,
            ))
            continue

        if ev.line_id not in valid_line_ids:
            all_quarantined.append(QuarantinedEvent(
                event_id=ev.event_id,
                reason=f"Unknown line_id '{ev.line_id}'",
                raw=ev.raw,
            ))
            continue

        cleaned_events.append(ev)

    for line in lines:
        line_rules  = [r for r in rules  if r.line_id == line.line_id]
        line_events = [e for e in cleaned_events if e.line_id == line.line_id]
        result = calculate_line(line, line_rules, line_events)
        line_results.append(result)
        all_quarantined.extend(result.quarantined_events)

    # Determine overall status
    any_ambiguous         = any(r.finding_type == FindingType.AMBIGUOUS        for r in line_results)
    any_insufficient      = any(r.finding_type == FindingType.INSUFFICIENT_DATA for r in line_results)
    any_quarantined       = bool(all_quarantined)

    if any_insufficient:
        status = EngineStatus.INSUFFICIENT_DATA
        reason = "One or more invoice lines have no pricing rule or insufficient data."
    elif any_ambiguous:
        status = EngineStatus.AMBIGUOUS
        reason = "One or more invoice lines have ambiguous pricing rules requiring human review."
    elif any_quarantined:
        status = EngineStatus.PARTIAL
        reason = f"{len(all_quarantined)} usage event(s) were quarantined; calculation continued with valid events."
    else:
        status = EngineStatus.OK
        reason = ""

    # Total difference is the sum of line differences; unresolvable lines have difference_cents=0
    # and do not produce phantom full refunds.
    total_original = sum(r.original_amount_cents for r in line_results)
    total_difference = sum(r.difference_cents for r in line_results)
    total_recalculated = total_original + total_difference

    return EngineResult(
        status=status,
        status_reason=reason,
        line_results=line_results,
        total_original_billed_cents=total_original,
        total_recalculated_cents=total_recalculated,
        total_difference_cents=total_difference,
        quarantined_events=all_quarantined,
        result_hash=_compute_input_hash(lines, rules, events),
    )
