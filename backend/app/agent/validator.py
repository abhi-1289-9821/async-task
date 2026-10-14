"""
agent/validator.py
==================
Rigorous verification layer enforcing:
1. Citation Integrity: all cited result IDs must strictly exist in the engine calculation.
2. Financial Consistency: finding type must not contradict deterministic math.
3. Option Validity: credit recommendations must anchor to real overcharged line results.
"""

import logging
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

VALID_FINDING_TYPES = {
    "CONFIRMED_CALCULATION_DISCREPANCY",
    "POSSIBLE_DISCREPANCY",
    "CONTRACT_AMBIGUITY",
    "INSUFFICIENT_EVIDENCE",
    "NO_DISCREPANCY",
    "UNRESOLVED",
}


class LLMFindingPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    finding_type: str = "UNRESOLVED"
    summary_narrative: str = ""
    calculation_line_result_id: Optional[int] = None
    citation_ids: list[str] = Field(default_factory=list)
    verified_facts: list[str] = Field(default_factory=list)
    possible_explanations: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    missing_evidence_questions: list[str] = Field(default_factory=list)


def validate_llm_payload(
    raw_dict: dict[str, Any],
    line_results: list[dict[str, Any]],
) -> tuple[bool, dict[str, Any], list[str]]:
    """
    Validates LLM finding JSON against schema, verifies line_result_id against this run,
    and validates that finding_type is recognized.
    """
    errors = []
    try:
        model = LLMFindingPayload.model_validate(raw_dict)
        sanitized = model.model_dump()
    except Exception as e:
        return False, {"finding_type": "UNRESOLVED", "summary_narrative": "Schema validation failed"}, [f"LLM JSON schema error: {e}"]

    if sanitized["finding_type"] not in VALID_FINDING_TYPES:
        errors.append(f"Invalid finding_type '{sanitized['finding_type']}' from LLM; defaulting to UNRESOLVED")
        sanitized["finding_type"] = "UNRESOLVED"

    # Validate calculation_line_result_id against this run's line results
    valid_db_ids = {lr.get("id") for lr in line_results if lr.get("id") is not None}
    if sanitized["calculation_line_result_id"] is not None:
        if sanitized["calculation_line_result_id"] not in valid_db_ids:
            errors.append(
                f"Bogus calculation_line_result_id '{sanitized['calculation_line_result_id']}'; not present in this run"
            )
            sanitized["calculation_line_result_id"] = None

    return (len(errors) == 0), sanitized, errors


def validate_citations(
    finding: dict[str, Any],
    valid_result_ids: list[str],
) -> tuple[bool, list[str], list[str]]:
    """
    Validates that all citation_ids in the finding match valid evidence identifiers
    (calculation result_ids, invoice line_ids, contract rule_ids, or usage event_ids).
    Returns (passed, sanitized_citation_ids, error_messages).
    """
    citations = finding.get("citation_ids") or []
    if not isinstance(citations, list):
        return False, [], ["Citation IDs must be a list"]

    errors = []
    valid_set = set(valid_result_ids)
    sanitized = []

    for c in citations:
        c_str = str(c)
        if c_str in valid_set:
            sanitized.append(c_str)
        else:
            errors.append(f"Invalid citation ID '{c_str}'; not found in calculation line results or evidence")

    passed = (len(errors) == 0) and (len(sanitized) > 0 or len(valid_set) == 0)
    return passed, sanitized, errors


def derive_engine_finding_type(
    line_results: list[dict[str, Any]],
    calculation_status: str = "OK",
) -> str:
    """
    Derives deterministic finding type from billing engine results with strict precedence:
      1. any INSUFFICIENT_DATA -> INSUFFICIENT_EVIDENCE
      2. else any AMBIGUOUS -> CONTRACT_AMBIGUITY
      3. else any overcharge (difference_cents < 0) -> CONFIRMED_CALCULATION_DISCREPANCY
      4. else NO_DISCREPANCY
    """
    # 1. Any INSUFFICIENT_DATA
    if calculation_status == "INSUFFICIENT_DATA" or any(lr.get("finding_type") == "INSUFFICIENT_DATA" for lr in line_results):
        return "INSUFFICIENT_EVIDENCE"

    # 2. Else any AMBIGUOUS
    if calculation_status == "AMBIGUOUS" or any(lr.get("finding_type") == "AMBIGUOUS" for lr in line_results):
        return "CONTRACT_AMBIGUITY"

    # 3. Else any overcharge (difference_cents < 0 means customer was billed more than recalculated)
    if any(lr.get("difference_cents") is not None and lr.get("difference_cents") < 0 for lr in line_results):
        return "CONFIRMED_CALCULATION_DISCREPANCY"

    # 4. Else NO_DISCREPANCY
    return "NO_DISCREPANCY"


def generate_engine_narrative(
    engine_finding_type: str,
    line_results: list[dict[str, Any]],
    calculation_status: str = "OK",
) -> str:
    """Generates deterministic, mathematically consistent narrative when AI narrative contradicts engine."""
    if engine_finding_type == "INSUFFICIENT_EVIDENCE":
        return "Deterministic billing engine calculation indicates insufficient telemetry or contract data to recalculate line items. Additional evidence or rule definitions are required to complete investigation."
    elif engine_finding_type == "CONTRACT_AMBIGUITY":
        ambig_lines = [lr.get("line_id") for lr in line_results if lr.get("finding_type") == "AMBIGUOUS"]
        lines_desc = ", ".join(ambig_lines) if ambig_lines else "disputed line items"
        return f"Deterministic billing engine identified competing contract interpretations for {lines_desc}. Recalculated amount cannot be finalized until a reviewer chooses an interpretation."
    elif engine_finding_type == "CONFIRMED_CALCULATION_DISCREPANCY":
        overcharged = [lr for lr in line_results if lr.get("difference_cents") is not None and lr.get("difference_cents") < 0]
        total_overcharge = sum(abs(lr.get("difference_cents", 0)) for lr in overcharged)
        lines_summary = ", ".join(f"{lr.get('line_id')} (billed {lr.get('original_amount_cents')}¢, recalculated {lr.get('recalculated_amount_cents')}¢)" for lr in overcharged)
        return f"Deterministic billing engine confirmed an overcharge totaling {total_overcharge}¢ across line item(s): {lines_summary}. Discrepancy is eligible for credit approval."
    else:
        return "Deterministic billing engine verified all line items against contractual pricing rules and telemetry events. All billed amounts match recalculated figures; no discrepancy found."


def validate_consistency(
    finding: dict[str, Any],
    calculation_status: str,
    total_difference_cents: int,
    line_results: list[dict[str, Any]],
) -> tuple[bool, str, list[str]]:
    """
    Verifies that the model's finding type matches the deterministic engine-derived type.
    If the model contradicts the engine:
      - consistency_check_passed is set to False
      - final finding type is overridden to the engine-derived type
      - validation notes record the exact contradiction
    Returns (consistency_check_passed, final_finding_type, validation_notes).
    """
    model_type = finding.get("finding_type", "UNRESOLVED")
    engine_type = derive_engine_finding_type(line_results, calculation_status)
    notes = []

    if model_type != engine_type:
        notes.append(
            f"AI finding type '{model_type}' contradicted deterministic engine result '{engine_type}'; overridden to '{engine_type}'"
        )
        return False, engine_type, notes

    return True, engine_type, []


def sanitize_resolution_options(
    options: list[dict[str, Any]],
    line_results: list[dict[str, Any]],
    finding_type: str = "CONFIRMED_CALCULATION_DISCREPANCY",
) -> list[dict[str, Any]]:
    """
    Validates resolution options against the validated finding type and line results.
    - RECOMMEND_CREDIT is ONLY allowed if finding_type is CONFIRMED_CALCULATION_DISCREPANCY
      and anchored to a verified overcharged line result.
    - If finding is UNRESOLVED or CONTRACT_AMBIGUITY, RECOMMEND_CREDIT is forbidden.
    """
    line_results_by_id = {lr.get("id"): lr for lr in line_results if lr.get("id") is not None}
    sanitized: list[dict[str, Any]] = []

    for opt in options:
        opt_type = opt.get("option_type", "CLOSE_NO_ADJUSTMENT")
        description = opt.get("description", "")
        lr_id = opt.get("calculation_line_result_id")

        if opt_type == "RECOMMEND_CREDIT":
            # Forbid credit recommendations if finding is not confirmed discrepancy
            if finding_type != "CONFIRMED_CALCULATION_DISCREPANCY":
                logger.warning(
                    "Rejected RECOMMEND_CREDIT option: finding_type is '%s' (only CONFIRMED_CALCULATION_DISCREPANCY can recommend credit)",
                    finding_type,
                )
                continue
            # Must point to an existing line result with an overcharge
            lr = line_results_by_id.get(lr_id)
            if not lr or lr.get("difference_cents", 0) >= 0:
                logger.warning(
                    "Rejected RECOMMEND_CREDIT option: line_result_id %s has no overcharge (diff: %s)",
                    lr_id,
                    lr.get("difference_cents") if lr else "None",
                )
                continue
        elif opt_type == "CREDIT_UNDISPUTED_PORTION":
            if finding_type != "CONTRACT_AMBIGUITY":
                logger.warning(
                    "Rejected CREDIT_UNDISPUTED_PORTION option: finding_type is '%s' (only CONTRACT_AMBIGUITY can credit undisputed portion)",
                    finding_type,
                )
                continue
            lr = line_results_by_id.get(lr_id)
            undisputed_amt = lr.get("undisputed_overcharge_cents") if lr else None
            if not lr or not undisputed_amt or undisputed_amt <= 0:
                logger.warning(
                    "Rejected CREDIT_UNDISPUTED_PORTION option: line_result_id %s has no positive undisputed overcharge",
                    lr_id,
                )
                continue
        elif lr_id not in line_results_by_id:
            lr_id = None

        sanitized.append({
            "option_type": opt_type,
            "description": description,
            "calculation_line_result_id": lr_id,
        })

    if finding_type == "CONTRACT_AMBIGUITY":
        has_credit_undisputed = any(o.get("option_type") == "CREDIT_UNDISPUTED_PORTION" for o in sanitized)
        if not has_credit_undisputed:
            for lr in line_results:
                undisputed = lr.get("undisputed_overcharge_cents")
                if undisputed and undisputed > 0:
                    sanitized.insert(0, {
                        "option_type": "CREDIT_UNDISPUTED_PORTION",
                        "description": f"Credit undisputed portion of {undisputed}¢ (billed amount exceeds highest contract interpretation); remainder awaits contract clarification.",
                        "calculation_line_result_id": lr.get("id"),
                    })
                    break

    if not sanitized:
        if finding_type == "CONTRACT_AMBIGUITY":
            sanitized.append({
                "option_type": "ESCALATE",
                "description": "Escalate to account management and legal counsel to determine the intended contractual tier model.",
                "calculation_line_result_id": None,
            })
        elif finding_type == "INSUFFICIENT_EVIDENCE":
            sanitized.append({
                "option_type": "REQUEST_EVIDENCE",
                "description": "Request missing usage telemetry or contract amendment documentation.",
                "calculation_line_result_id": None,
            })
        elif finding_type == "UNRESOLVED":
            sanitized.append({
                "option_type": "ESCALATE",
                "description": "Escalate for manual reviewer adjudication due to contradictory or unverified evidence.",
                "calculation_line_result_id": None,
            })
        else:
            sanitized.append({
                "option_type": "CLOSE_NO_ADJUSTMENT",
                "description": "Close dispute with no financial adjustment; billing matches contractual terms.",
                "calculation_line_result_id": None,
            })

    return sanitized


import re
from decimal import Decimal


def extract_monetary_amounts_cents(text: str) -> list[tuple[str, int, bool]]:
    """
    Extracts explicit dollar ($X or $X.YY) and cent (X¢, X cents) amounts from narrative text.
    Returns list of (raw_token, amount_cents, is_rate).
    is_rate is True if the amount is explicitly followed by a unit rate specifier (e.g. /unit, per call).
    """
    if not text:
        return []
    results = []

    # Match $50, $50.00, $0.50, $1,000.00, $9,999.99 (with optional rate suffix)
    dollar_matches = re.finditer(
        r"\$([0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)(\s*(?:/|per\s+)[a-zA-Z]+)?",
        text,
        re.IGNORECASE,
    )
    for m in dollar_matches:
        raw_str = m.group(0)
        num_str = m.group(1).replace(",", "")
        is_rate = bool(m.group(2))
        try:
            val_cents = int((Decimal(num_str) * 100).to_integral_value())
            results.append((raw_str, val_cents, is_rate))
        except Exception:
            pass

    # Match 5,000 USD, 5000 USD, 50.00 USD, 5,000 dollars, 50 dollars (trailing USD/dollars)
    usd_matches = re.finditer(
        r"(?<![0-9\$])([0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)\s*(?:USD|dollars?)(\s*(?:/|per\s+)[a-zA-Z]+)?\b",
        text,
        re.IGNORECASE,
    )
    for m in usd_matches:
        raw_str = m.group(0).strip()
        num_str = m.group(1).replace(",", "")
        is_rate = bool(m.group(2))
        try:
            val_cents = int((Decimal(num_str) * 100).to_integral_value())
            results.append((raw_str, val_cents, is_rate))
        except Exception:
            pass

    # Match 5000¢, 5000 cents, 5000 cent
    cent_matches = re.finditer(
        r"(?<![0-9])([0-9]+)\s*(?:¢|cents?)(\s*(?:/|per\s+)[a-zA-Z]+)?(?![a-zA-Z0-9])",
        text,
        re.IGNORECASE,
    )
    for m in cent_matches:
        raw_str = m.group(0).strip()
        num_str = m.group(1)
        is_rate = bool(m.group(2))
        try:
            val_cents = int(num_str)
            results.append((raw_str, val_cents, is_rate))
        except Exception:
            pass

    return results


def validate_narrative_amounts(
    finding: dict[str, Any],
    line_results: list[dict[str, Any]],
    summary: dict[str, Any],
    contract_rules: list[dict[str, Any]] | None = None,
    adjustments: list[dict[str, Any]] | None = None,
    case_data: dict[str, Any] | None = None,
) -> tuple[bool, list[str]]:
    """
    Scans AI finding narrative, facts, and explanations for fabricated dollar amounts.
    All monetary values mentioned in the text must be anchored to numbers emitted
    by the deterministic billing engine, contract rules, case adjustments, or valid rate figures.
    """
    allowed_cents = {0}
    allowed_rate_cents = set()

    for lr in line_results:
        if lr.get("original_amount_cents") is not None:
            allowed_cents.add(lr["original_amount_cents"])
        if lr.get("recalculated_amount_cents") is not None:
            allowed_cents.add(lr["recalculated_amount_cents"])
        if lr.get("difference_cents") is not None:
            allowed_cents.add(abs(lr["difference_cents"]))
        if lr.get("applied_minimum_commit_cents"):
            allowed_cents.add(lr["applied_minimum_commit_cents"])
        for interp in lr.get("interpretations") or []:
            if isinstance(interp, dict):
                amt = interp.get("recalculated_amount_cents", 0)
                if amt is not None:
                    allowed_cents.add(amt)
                    if lr.get("original_amount_cents") is not None:
                        allowed_cents.add(abs(amt - lr["original_amount_cents"]))

    for rule in (contract_rules or []):
        r_rate = rule.get("rate_cents", 0)
        if r_rate is not None:
            allowed_cents.add(r_rate)
            allowed_rate_cents.add(r_rate)
        if rule.get("overage_rate_cents") is not None:
            allowed_cents.add(rule["overage_rate_cents"])
            allowed_rate_cents.add(rule["overage_rate_cents"])
        if rule.get("minimum_commit_cents") is not None:
            allowed_cents.add(rule["minimum_commit_cents"])
        for tier in rule.get("tiers") or []:
            if isinstance(tier, dict):
                t_price = tier.get("price_per_unit_cents", 0) or tier.get("rate_cents", 0)
                if t_price is not None:
                    allowed_cents.add(t_price)
                    allowed_rate_cents.add(t_price)

    for adj in (adjustments or []):
        amt = adj.get("amount_cents")
        if amt is not None:
            allowed_cents.add(amt)

    if case_data:
        disp_amt = case_data.get("disputed_amount_cents")
        if disp_amt is not None:
            allowed_cents.add(disp_amt)

    if summary:
        if summary.get("total_original_billed_cents") is not None:
            allowed_cents.add(summary["total_original_billed_cents"])
        if summary.get("total_recalculated_cents") is not None:
            allowed_cents.add(summary["total_recalculated_cents"])
        if summary.get("total_difference_cents") is not None:
            allowed_cents.add(abs(summary["total_difference_cents"]))

    texts_to_scan = []
    if finding.get("raw_ai_text"):
        texts_to_scan.append(str(finding["raw_ai_text"]))
    if finding.get("summary_narrative"):
        texts_to_scan.append(str(finding["summary_narrative"]))
    for f in finding.get("verified_facts") or []:
        texts_to_scan.append(str(f))
    for p in finding.get("possible_explanations") or []:
        texts_to_scan.append(str(p))

    unanchored = []
    for text in texts_to_scan:
        extracted = extract_monetary_amounts_cents(text)
        for raw_token, cents, is_rate in extracted:
            # If explicit rate token (e.g. $0.10/unit) and matches contract rate, or is valid rate
            if is_rate and (cents in allowed_rate_cents or cents in allowed_cents):
                continue
            if cents not in allowed_cents:
                unanchored.append(
                    f"Fabricated monetary amount '{raw_token}' ({cents}¢) detected in AI narrative; not anchored to engine calculation"
                )

    passed = (len(unanchored) == 0)
    return passed, unanchored

