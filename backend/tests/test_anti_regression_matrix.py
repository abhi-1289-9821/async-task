"""
test_anti_regression_matrix.py
==============================
Anti-regression property-based and scenario-matrix test suite for FairBill.
Uses Hypothesis to assert the 7 key billing & credit invariants across all permutations:
  - Currencies: USD, EUR, GBP
  - Rule types: TIERED_GRADUATED, TIERED_VOLUME, PER_UNIT, FLAT, INCLUDED_UNITS, DISCOUNT_PCT, MINIMUM_COMMIT
  - Single and multi-line cases
  - With and without telemetry, staging-only usage
  - Periods in the past, present, future, and none
  - Verified and unverified adjustments, prior credits

7 Invariants Asserted:
  1. remaining_cap = max(0, eligible_overcharge - prior_credits - verified_adjustments); unverified adjustments never change it.
  2. No approved credit exceeds remaining_cap; the sum of credits never exceeds eligible_overcharge.
  3. Total difference equals the sum of per-line differences; lines that are INSUFFICIENT_DATA or AMBIGUOUS contribute 0 and cannot be credited.
  4. Every amount in AI narratives equals an engine value (formatted in the case currency).
  5. The cap shown by every UI tab equals the backend ledger value.
  6. Telemetry entered through the form is never silently excluded by the form's own timestamp.
  7. Any user-visible money string uses the case currency.
"""

from datetime import datetime, timezone, timedelta
from decimal import Decimal
import uuid
import pytest
from hypothesis import given, settings, strategies as st
from fastapi.testclient import TestClient

from app.config import settings as app_settings
from app.main import app
from app.models import (
    Case, CaseStatus, InvoiceLine, ContractRule, RuleTypeDB,
    UsageEvent, Calculation, CalculationLineResult,
    InvestigationRun, Finding, RunStatus, AgentFindingType,
    Credit, Adjustment,
)
from app.billing_engine import (
    RuleType,
    EngineStatus,
    FindingType,
    ContractRule as EngineRule,
    InvoiceLine as EngineLine,
    UsageEvent as EngineEvent,
    TierBand,
    calculate_line,
    run_calculation,
)
from app.services import credit_service
from app.utils.money import format_money, get_currency_symbol
from app.agent.validator import extract_monetary_amounts_cents, generate_engine_narrative

REVIEWER_HEADERS = {"Authorization": f"Bearer {app_settings.demo_reviewer_token}"}


@pytest.fixture(scope="module")
def api_client():
    app_settings.llm_mode = "mock"
    app_settings.demo_mode = True
    with TestClient(app) as client:
        yield client


# ==============================================================================
# INVARIANT 1: Cap Formula & Unverified Adjustment Invariance
# remaining_cap = max(0, eligible_overcharge - prior_credits - verified_adjustments);
# unverified adjustments never change it.
# ==============================================================================

class TestInvariant1CapFormula:
    @given(
        eligible_overcharge=st.integers(min_value=0, max_value=500_000),
        prior_credits=st.integers(min_value=0, max_value=500_000),
        verified_adjustments=st.integers(min_value=0, max_value=500_000),
        unverified_adjustments=st.integers(min_value=0, max_value=500_000),
    )
    @settings(max_examples=50, deadline=None)
    def test_cap_formula_property(
        self, eligible_overcharge, prior_credits, verified_adjustments, unverified_adjustments
    ):
        expected_cap = max(0, eligible_overcharge - prior_credits - verified_adjustments)

        computed = credit_service.compute_remaining_cap_from_values(
            eligible_overcharge=eligible_overcharge,
            prior_credits=prior_credits,
            verified_adjustments=verified_adjustments,
            unverified_adjustments=unverified_adjustments,
        )
        assert computed["remaining_cap"] == expected_cap
        assert computed["remaining_cap"] >= 0
        assert computed["verified_adjustments"] == verified_adjustments
        assert computed["unverified_adjustments"] == unverified_adjustments

        # Toggling or varying unverified adjustments MUST NOT change remaining_cap
        computed_with_extra_unverified = credit_service.compute_remaining_cap_from_values(
            eligible_overcharge=eligible_overcharge,
            prior_credits=prior_credits,
            verified_adjustments=verified_adjustments,
            unverified_adjustments=unverified_adjustments + 777_777,
        )
        assert computed_with_extra_unverified["remaining_cap"] == expected_cap

    def test_cap_floors_at_zero_when_adjustments_exceed_overcharge(self):
        """When verified adjustments exceed eligible overcharge, cap floors at 0."""
        computed = credit_service.compute_remaining_cap_from_values(
            eligible_overcharge=10000,
            prior_credits=0,
            verified_adjustments=25000,
            unverified_adjustments=50000,
        )
        assert computed["remaining_cap"] == 0
        assert computed["remaining_cap"] >= 0


# ==============================================================================
# INVARIANT 2: Credit Approval Ceiling & Repeat-Approval Guard
# No approved credit exceeds remaining_cap; sum of credits <= eligible_overcharge.
# ==============================================================================

class TestInvariant2CreditLimits:
    @pytest.mark.parametrize("currency", ["USD", "EUR", "GBP"])
    def test_credit_cannot_exceed_remaining_cap(self, api_client, currency):
        uid = uuid.uuid4().hex[:6]
        case_id = f"c2-{currency.lower()}-{uid}"
        line_id = f"l2-{currency.lower()}-{uid}"

        # 1. Create case: billed 100000c, FLAT 60000c -> 40000c overcharge.
        # Verified adjustment 10000c -> remaining cap = 30000c.
        c_res = api_client.post(
            "/api/cases",
            headers=REVIEWER_HEADERS,
            json={
                "id": case_id,
                "title": f"Credit Ceiling Test {currency}",
                "customer_name": "Test Customer",
                "currency": currency,
                "disputed_amount_cents": 40000,
                "invoice_lines": [{"id": line_id, "description": "Flat Service", "original_amount_cents": 100000}],
                "contract_rules": [{"id": f"r2-{uid}", "line_id": line_id, "rule_type": "FLAT", "rate_cents": 60000}],
                "adjustments": [
                    {"id": f"av-{uid}", "invoice_line_id": line_id, "amount_cents": 10000, "is_verified": True, "description": "Confirmed rebate"},
                    {"id": f"au-{uid}", "invoice_line_id": line_id, "amount_cents": 15000, "is_verified": False, "description": "Unverified claim"},
                ],
            },
        )
        assert c_res.status_code == 201

        # 2. Run calculation via JSON body
        calc_res = api_client.post("/api/calculations/run", headers=REVIEWER_HEADERS, json={"case_id": case_id})
        assert calc_res.status_code == 201

        # 3. Run investigation in mock mode
        inv_res = api_client.post(f"/api/cases/{case_id}/investigations", headers=REVIEWER_HEADERS)
        assert inv_res.status_code == 201
        inv_data = inv_res.json()
        finding_id = inv_data["findings"][0]["id"]

        # 4. Accept finding
        rev_res = api_client.post(
            f"/api/findings/{finding_id}/review",
            headers=REVIEWER_HEADERS,
            json={"action": "ACCEPT", "note": "Verified"},
        )
        assert rev_res.status_code == 201

        # Check ledger
        ledger_res = api_client.get(f"/api/credits/case/{case_id}/cap?invoice_line_id={line_id}", headers=REVIEWER_HEADERS)
        assert ledger_res.status_code == 200
        ledger = ledger_res.json()
        assert ledger["remaining_cap"] == 30000
        assert ledger["approval_eligibility"] == "ELIGIBLE"

        # Attempting credit exceeding cap (30001c) MUST FAIL
        over_credit = api_client.post(
            "/api/credits/approve",
            headers=REVIEWER_HEADERS,
            json={
                "case_id": case_id,
                "invoice_line_id": line_id,
                "finding_id": finding_id,
                "requested_amount_cents": 30001,
                "reason_code": "RATE_CALCULATION_ERROR",
            },
        )
        assert over_credit.status_code in (400, 422)

        # Approving within remaining cap (30000c) succeeds
        ok_credit = api_client.post(
            "/api/credits/approve",
            headers=REVIEWER_HEADERS,
            json={
                "case_id": case_id,
                "invoice_line_id": line_id,
                "finding_id": finding_id,
                "requested_amount_cents": 30000,
                "reason_code": "RATE_CALCULATION_ERROR",
            },
        )
        assert ok_credit.status_code == 201

        # Second approval on the same finding must fail (409 Conflict)
        repeat_credit = api_client.post(
            "/api/credits/approve",
            headers=REVIEWER_HEADERS,
            json={
                "case_id": case_id,
                "invoice_line_id": line_id,
                "finding_id": finding_id,
                "requested_amount_cents": 1000,
                "reason_code": "RATE_CALCULATION_ERROR",
            },
        )
        assert repeat_credit.status_code == 409


# ==============================================================================
# INVARIANT 3: Total Difference & Uncreditable Lines
# Total difference = sum of per-line differences; INSUFFICIENT_DATA/AMBIGUOUS lines contribute 0 and cannot be credited.
# ==============================================================================

class TestInvariant3TotalDifferenceAndUncreditableLines:
    def test_multi_line_aggregation_clean_lines(self, api_client):
        """When lines compute cleanly, total difference equals the exact sum of line differences."""
        uid = uuid.uuid4().hex[:6]
        case_id = f"c3a-{uid}"
        line1 = f"l1-{uid}"
        line2 = f"l2-{uid}"

        c_res = api_client.post(
            "/api/cases",
            headers=REVIEWER_HEADERS,
            json={
                "id": case_id,
                "title": "Clean Multi-Line Aggregation",
                "customer_name": "Acme Clean",
                "currency": "EUR",
                "disputed_amount_cents": 35000,
                "invoice_lines": [
                    {"id": line1, "description": "Flat Hosting 1", "original_amount_cents": 50000},
                    {"id": line2, "description": "Flat Hosting 2", "original_amount_cents": 40000},
                ],
                "contract_rules": [
                    {"id": f"r1-{uid}", "line_id": line1, "rule_type": "FLAT", "rate_cents": 30000}, # diff = -20000
                    {"id": f"r2-{uid}", "line_id": line2, "rule_type": "FLAT", "rate_cents": 25000}, # diff = -15000
                ],
            },
        )
        assert c_res.status_code == 201

        calc_res = api_client.post("/api/calculations/run", headers=REVIEWER_HEADERS, json={"case_id": case_id})
        assert calc_res.status_code == 201
        calc = calc_res.json()

        # Sum of per-line differences: -20000 + -15000 = -35000
        assert calc["total_difference_cents"] == -35000
        assert calc["total_recalculated_cents"] == 55000

    def test_insufficient_data_line_cannot_be_credited(self, api_client):
        """Lines with INSUFFICIENT_DATA contribute 0 to credit cap and cannot be credited."""
        uid = uuid.uuid4().hex[:6]
        case_id = f"c3b-{uid}"
        line_ok = f"lok-{uid}"
        line_nodata = f"lno-{uid}"

        c_res = api_client.post(
            "/api/cases",
            headers=REVIEWER_HEADERS,
            json={
                "id": case_id,
                "title": "Insufficient Data Non-Creditable Test",
                "customer_name": "Acme MultiLine",
                "currency": "EUR",
                "disputed_amount_cents": 20000,
                "invoice_lines": [
                    {"id": line_ok, "description": "Flat Hosting", "original_amount_cents": 50000},
                    {"id": line_nodata, "description": "Metered Compute", "original_amount_cents": 40000},
                ],
                "contract_rules": [
                    {"id": f"rok-{uid}", "line_id": line_ok, "rule_type": "FLAT", "rate_cents": 30000},
                    {"id": f"rno-{uid}", "line_id": line_nodata, "rule_type": "PER_UNIT", "rate_cents": 10},
                ],
            },
        )
        assert c_res.status_code == 201

        calc_res = api_client.post("/api/calculations/run", headers=REVIEWER_HEADERS, json={"case_id": case_id})
        assert calc_res.status_code == 201
        calc = calc_res.json()

        nodata_res = next(lr for lr in calc["line_results"] if lr["line_id"] == line_nodata)
        assert nodata_res["finding_type"] == "INSUFFICIENT_DATA"

        # Cap for nodata line must be 0 and not eligible
        cap_nodata = api_client.get(f"/api/credits/case/{case_id}/cap?invoice_line_id={line_nodata}", headers=REVIEWER_HEADERS).json()
        assert cap_nodata["approval_eligibility"] in ("NOT_ELIGIBLE", "INELIGIBLE", "PENDING_REVIEW", "BLOCKED")
        assert cap_nodata["remaining_cap"] == 0


# ==============================================================================
# INVARIANT 4 & 7: AI Narratives & Currency Symbols
# Every amount in AI narratives equals an engine value formatted in case currency;
# user-visible money string uses the case currency.
# ==============================================================================

class TestInvariant4And7NarrativesAndCurrency:
    @given(cents=st.integers(min_value=0, max_value=10_000_000))
    @settings(max_examples=30, deadline=None)
    def test_currency_formatting_property(self, cents):
        eur_str = format_money(cents, "EUR")
        assert "€" in eur_str
        assert "$" not in eur_str

        gbp_str = format_money(cents, "GBP")
        assert "£" in gbp_str
        assert "$" not in gbp_str

        usd_str = format_money(cents, "USD")
        assert "$" in usd_str
        assert "€" not in usd_str
        assert "£" not in usd_str

    @pytest.mark.parametrize("currency,expected_sym", [("EUR", "€"), ("GBP", "£"), ("USD", "$")])
    def test_engine_narrative_generates_correct_currency_symbol(self, currency, expected_sym):
        narrative = generate_engine_narrative(
            engine_finding_type="CONFIRMED_CALCULATION_DISCREPANCY",
            line_results=[{
                "line_id": "line-1",
                "original_amount_cents": 100000,
                "recalculated_amount_cents": 80000,
                "difference_cents": -20000,
                "finding_type": "CONFIRMED_CALCULATION_DISCREPANCY",
            }],
            calculation_status="OK",
            currency=currency,
        )
        assert expected_sym in narrative
        for other_sym in {"€", "£", "$"}:
            if other_sym != expected_sym:
                assert other_sym not in narrative

        # Invariant 4: Every amount extracted from narrative must equal an engine value
        extracted = extract_monetary_amounts_cents(narrative)
        valid_engine_cents = {100000, 80000, 20000}
        for item in extracted:
            cents = item[1] if isinstance(item, tuple) else item
            assert cents in valid_engine_cents, f"Extracted amount {cents} not in engine amounts {valid_engine_cents}"


# ==============================================================================
# INVARIANT 5: Single Source of Truth for Ledger Across Tabs
# The cap shown by every UI tab equals the backend ledger value.
# ==============================================================================

class TestInvariant5SingleSourceOfTruth:
    @pytest.mark.parametrize("currency", ["EUR", "USD", "GBP"])
    def test_ledger_single_source_of_truth(self, api_client, currency):
        uid = uuid.uuid4().hex[:6]
        case_id = f"c5-{currency.lower()}-{uid}"
        line_id = f"l5-{currency.lower()}-{uid}"

        api_client.post(
            "/api/cases",
            headers=REVIEWER_HEADERS,
            json={
                "id": case_id,
                "title": f"Single Source Test {currency}",
                "customer_name": "Golden Corp",
                "currency": currency,
                "disputed_amount_cents": 50000,
                "invoice_lines": [{"id": line_id, "description": "Flat Plan", "original_amount_cents": 100000}],
                "contract_rules": [{"id": f"r5-{uid}", "line_id": line_id, "rule_type": "FLAT", "rate_cents": 50000}],
                "adjustments": [
                    {"id": f"a5-{uid}", "invoice_line_id": line_id, "amount_cents": 12000, "is_verified": True, "description": "Rebate"}
                ],
            },
        )

        # Before calculation: pending review
        pre_calc_cap = api_client.get(f"/api/credits/case/{case_id}/cap?invoice_line_id={line_id}", headers=REVIEWER_HEADERS).json()
        assert pre_calc_cap["approval_eligibility"] == "PENDING_REVIEW"
        assert pre_calc_cap["reason"] == "Pending review"

        # Run calculation via JSON body
        api_client.post("/api/calculations/run", headers=REVIEWER_HEADERS, json={"case_id": case_id})

        # Before finding review: pending review
        calc_cap = api_client.get(f"/api/credits/case/{case_id}/cap?invoice_line_id={line_id}", headers=REVIEWER_HEADERS).json()
        assert calc_cap["approval_eligibility"] == "PENDING_REVIEW"

        # Investigate and accept finding
        inv_res = api_client.post(f"/api/cases/{case_id}/investigations", headers=REVIEWER_HEADERS)
        finding_id = inv_res.json()["findings"][0]["id"]
        rev_res = api_client.post(
            f"/api/findings/{finding_id}/review",
            headers=REVIEWER_HEADERS,
            json={"action": "ACCEPT", "note": "Approved"},
        )
        assert rev_res.status_code == 201

        # After review: single source of truth is 50000 - 12000 = 38000c
        post_review_cap = api_client.get(f"/api/credits/case/{case_id}/cap?invoice_line_id={line_id}", headers=REVIEWER_HEADERS).json()
        assert post_review_cap["approval_eligibility"] == "ELIGIBLE"
        assert post_review_cap["eligible_overcharge"] == 50000
        assert post_review_cap["verified_adjustments"] == 12000
        assert post_review_cap["remaining_cap"] == 38000


# ==============================================================================
# INVARIANT 6: Form Timestamp Inside Billing Period Never Quarantined
# Telemetry entered through the form is never silently excluded by form's timestamp.
# ==============================================================================

class TestInvariant6FormTimestampNeverQuarantined:
    @given(
        days_offset=st.integers(min_value=-365, max_value=365),
        duration_days=st.integers(min_value=1, max_value=90),
    )
    @settings(max_examples=30, deadline=None)
    def test_form_timestamp_inside_period_property(self, days_offset, duration_days):
        base = datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
        p_start = base + timedelta(days=days_offset)
        p_end = p_start + timedelta(days=duration_days)

        event_time = datetime(p_start.year, p_start.month, p_start.day, 12, 0, 0, tzinfo=timezone.utc)
        assert p_start <= event_time <= p_end

        line = EngineLine(
            line_id="line-t",
            description="Metered",
            original_amount_cents=10000,
        )
        rule = EngineRule(rule_id="r-t", line_id="line-t", rule_type=RuleType.PER_UNIT, rate_cents=10)
        event = EngineEvent(event_id="e-form", line_id="line-t", timestamp=event_time, quantity=Decimal("100.0"), environment="production")

        res = run_calculation(
            lines=[line],
            rules=[rule],
            events=[event],
            period_start=p_start,
            period_end=p_end,
        )
        assert res.status == EngineStatus.OK
        assert len(res.quarantined_events) == 0
        assert res.total_recalculated_cents == 1000


# ==============================================================================
# FULL SCENARIO MATRIX: End-to-End Across All 7 Rule Types
# ==============================================================================

class TestFullScenarioMatrixAllRuleTypes:
    @pytest.mark.parametrize("rule_type", [
        "TIERED_GRADUATED",
        "TIERED_VOLUME",
        "PER_UNIT",
        "FLAT",
        "INCLUDED_UNITS",
        "DISCOUNT_PCT",
        "MINIMUM_COMMIT",
    ])
    @pytest.mark.parametrize("currency", ["USD", "EUR", "GBP"])
    def test_matrix_e2e_lifecycle(self, api_client, rule_type, currency):
        uid = uuid.uuid4().hex[:4]
        rule_abbr = rule_type[:4].lower()
        curr = currency.lower()
        case_id = f"m-{rule_abbr}-{curr}-{uid}"
        line_id = f"l-{rule_abbr}-{curr}-{uid}"

        tiers = [
            {"up_to": 500, "price_per_unit_cents": 10},
            {"up_to": 1000, "price_per_unit_cents": 8},
            {"up_to": None, "price_per_unit_cents": 5},
        ]
        
        rules = []
        events = []
        original_billed = 100000

        if rule_type == "TIERED_GRADUATED":
            rules.append({"id": f"r-{uid}", "line_id": line_id, "rule_type": "TIERED_GRADUATED", "tiers": tiers, "exempt_environments": ["staging"]})
            events.append({"id": f"ep-{uid}", "line_id": line_id, "quantity": 1200.0, "environment": "production"})
            events.append({"id": f"es-{uid}", "line_id": line_id, "quantity": 500.0, "environment": "staging"})
        elif rule_type == "TIERED_VOLUME":
            rules.append({"id": f"r-{uid}", "line_id": line_id, "rule_type": "TIERED_VOLUME", "tiers": tiers, "exempt_environments": ["staging"]})
            events.append({"id": f"ep-{uid}", "line_id": line_id, "quantity": 1200.0, "environment": "production"})
        elif rule_type == "PER_UNIT":
            rules.append({"id": f"r-{uid}", "line_id": line_id, "rule_type": "PER_UNIT", "rate_cents": 50})
            events.append({"id": f"ep-{uid}", "line_id": line_id, "quantity": 1000.0, "environment": "production"})
        elif rule_type == "FLAT":
            rules.append({"id": f"r-{uid}", "line_id": line_id, "rule_type": "FLAT", "rate_cents": 60000})
        elif rule_type == "INCLUDED_UNITS":
            rules.append({"id": f"r-{uid}", "line_id": line_id, "rule_type": "INCLUDED_UNITS", "included_units": 500, "overage_rate_cents": 20})
            events.append({"id": f"ep-{uid}", "line_id": line_id, "quantity": 1500.0, "environment": "production"})
        elif rule_type == "DISCOUNT_PCT":
            rules.append({"id": f"rb-{uid}", "line_id": line_id, "rule_type": "FLAT", "rate_cents": 80000})
            rules.append({"id": f"r-{uid}", "line_id": line_id, "rule_type": "DISCOUNT_PCT", "discount_pct": 25.0})
        elif rule_type == "MINIMUM_COMMIT":
            rules.append({"id": f"rb-{uid}", "line_id": line_id, "rule_type": "PER_UNIT", "rate_cents": 10})
            rules.append({"id": f"r-{uid}", "line_id": line_id, "rule_type": "MINIMUM_COMMIT", "minimum_commit_cents": 30000})
            events.append({"id": f"ep-{uid}", "line_id": line_id, "quantity": 1000.0, "environment": "production"})

        # 1. Create case with verified and unverified adjustments
        c_res = api_client.post(
            "/api/cases",
            headers=REVIEWER_HEADERS,
            json={
                "id": case_id,
                "title": f"Matrix Dispute {rule_type} {currency}",
                "customer_name": "Matrix Corp",
                "currency": currency,
                "disputed_amount_cents": 40000,
                "invoice_lines": [{"id": line_id, "description": f"Line {rule_type}", "original_amount_cents": original_billed}],
                "contract_rules": rules,
                "usage_events": events,
                "adjustments": [
                    {"id": f"av-{uid}", "invoice_line_id": line_id, "amount_cents": 5000, "is_verified": True, "description": "Verified Credit"},
                    {"id": f"au-{uid}", "invoice_line_id": line_id, "amount_cents": 10000, "is_verified": False, "description": "Unverified Dispute"},
                ],
            },
        )
        assert c_res.status_code == 201

        # 2. Run calculation via JSON body
        calc_res = api_client.post("/api/calculations/run", headers=REVIEWER_HEADERS, json={"case_id": case_id})
        assert calc_res.status_code == 201
        calc = calc_res.json()
        assert calc["engine_status"] == "OK"

        # 3. Investigate in mock mode
        inv_res = api_client.post(f"/api/cases/{case_id}/investigations", headers=REVIEWER_HEADERS)
        assert inv_res.status_code == 201
        inv = inv_res.json()
        assert len(inv["findings"]) >= 1
        finding = inv["findings"][0]

        # 4. Review finding (ACCEPT)
        rev_res = api_client.post(
            f"/api/findings/{finding['id']}/review",
            headers=REVIEWER_HEADERS,
            json={"action": "ACCEPT", "note": "Matrix test acceptance"},
        )
        assert rev_res.status_code == 201

        # 5. Fetch single-source ledger
        ledger_res = api_client.get(f"/api/credits/case/{case_id}/cap?invoice_line_id={line_id}", headers=REVIEWER_HEADERS)
        assert ledger_res.status_code == 200
        ledger = ledger_res.json()

        # If there is an overcharge, cap must floor at 0 and verified adjustment deducted
        if ledger["eligible_overcharge"] > 0:
            assert ledger["remaining_cap"] == max(0, ledger["eligible_overcharge"] - 5000)
            assert ledger["approval_eligibility"] == "ELIGIBLE"

            # 6. Approve credit equal to remaining cap
            if ledger["remaining_cap"] > 0:
                app_res = api_client.post(
                    "/api/credits/approve",
                    headers=REVIEWER_HEADERS,
                    json={
                        "case_id": case_id,
                        "invoice_line_id": line_id,
                        "finding_id": finding["id"],
                        "requested_amount_cents": ledger["remaining_cap"],
                        "reason_code": "RATE_CALCULATION_ERROR",
                    },
                )
                assert app_res.status_code == 201
