"""
agent/validator.py
==================
Rigorous verification layer enforcing:
1. Citation Integrity: all cited result IDs must strictly exist in the engine calculation.
2. Financial Consistency: finding type must not contradict deterministic math.
3. Option Validity: credit recommendations must anchor to real overcharged line results.
"""

import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field

from app.utils.money import format_money

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
    quarantined_events: Optional[list[dict[str, Any]]] = None,
) -> tuple[bool, dict[str, Any], list[str]]:
    """
    Validates LLM finding JSON against schema, verifies line_result_id against this run,
    validates that finding_type is recognized, and validates evidence questions.
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

    # Quality Gate (Task 5a): Clean & deduplicate missing_evidence_questions and open_questions.
    # Drop empty or duplicate questions. Drop all when finding is CONFIRMED_CALCULATION_DISCREPANCY and telemetry is complete.
    seen_meq = set()
    cleaned_meq = []
    for q in sanitized.get("missing_evidence_questions") or []:
        q_str = str(q).strip()
        if q_str and q_str not in seen_meq:
            seen_meq.add(q_str)
            cleaned_meq.append(q_str)

    telemetry_is_complete = not bool(quarantined_events)
    if sanitized["finding_type"] == "CONFIRMED_CALCULATION_DISCREPANCY" and telemetry_is_complete:
        cleaned_meq = []

    sanitized["missing_evidence_questions"] = cleaned_meq

    seen_oq = set()
    cleaned_oq = []
    for q in sanitized.get("open_questions") or []:
        q_str = str(q).strip()
        if q_str and q_str not in seen_oq:
            seen_oq.add(q_str)
            cleaned_oq.append(q_str)
    sanitized["open_questions"] = cleaned_oq

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
    currency: str = "USD",
) -> str:
    """Generates deterministic, mathematically consistent narrative formatted with the case currency."""
    if engine_finding_type == "INSUFFICIENT_EVIDENCE":
        return "Deterministic billing engine calculation indicates insufficient telemetry or contract data to recalculate line items. Additional evidence or rule definitions are required to complete investigation."
    elif engine_finding_type == "CONTRACT_AMBIGUITY":
        ambig_lines = [lr.get("line_id") for lr in line_results if lr.get("finding_type") == "AMBIGUOUS"]
        lines_desc = ", ".join(ambig_lines) if ambig_lines else "disputed line items"
        return f"Deterministic billing engine identified competing contract interpretations for {lines_desc}. Recalculated amount cannot be finalized until a reviewer chooses an interpretation."
    elif engine_finding_type == "CONFIRMED_CALCULATION_DISCREPANCY":
        overcharged = [lr for lr in line_results if lr.get("difference_cents") is not None and lr.get("difference_cents") < 0]
        total_overcharge = sum(abs(lr.get("difference_cents", 0)) for lr in overcharged)
        formatted_total = format_money(total_overcharge, currency)
        lines_summary = ", ".join(
            f"{lr.get('line_id')} (billed {format_money(lr.get('original_amount_cents'), currency)}, recalculated {format_money(lr.get('recalculated_amount_cents'), currency)})"
            for lr in overcharged
        )
        return f"Deterministic billing engine confirmed an overcharge totaling {formatted_total} across line item(s): {lines_summary}. Discrepancy is eligible for credit approval."
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
        # If the model cautiously labelled a clear overcharge as POSSIBLE_DISCREPANCY, reconcile with engine
        if model_type == "POSSIBLE_DISCREPANCY" and engine_type == "CONFIRMED_CALCULATION_DISCREPANCY":
            return True, engine_type, notes
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


MECHANISM_PATTERNS = {
    "FLAT": [re.compile(r"\bflat[\s-]rate\b", re.I), re.compile(r"\bflat[\s-]fee\b", re.I), re.compile(r"\bflat[\s-]pricing\b", re.I)],
    "PER_UNIT": [re.compile(r"\bper[\s-]unit\b", re.I), re.compile(r"\bunit[\s-]rate\b", re.I)],
    "TIERED_GRADUATED": [re.compile(r"\bgraduated\b", re.I), re.compile(r"\btiered[\s-]graduated\b", re.I)],
    "TIERED_VOLUME": [re.compile(r"\bvolume[\s-]tier\b", re.I), re.compile(r"\btiered[\s-]volume\b", re.I)],
    "INCLUDED_UNITS": [re.compile(r"\bincluded[\s-]units\b", re.I), re.compile(r"\boverage\b", re.I)],
    "DISCOUNT_PCT": [re.compile(r"\bdiscount\b", re.I), re.compile(r"\bpercentage[\s-]discount\b", re.I)],
    "MINIMUM_COMMIT": [re.compile(r"\bminimum[\s-]commit\b", re.I), re.compile(r"\bfloor\b", re.I)],
}


def validate_hypotheses_grounding(
    possible_explanations: list[str],
    contract_rules: list[dict[str, Any]] | None = None,
    line_results: list[dict[str, Any]] | None = None,
) -> list[str]:
    """
    Quality Gate (Task 5b): Validates that root-cause hypotheses are grounded in evidence.
    A hypothesis may only state a cause that is derivable from provided evidence;
    otherwise it must be 'Cause cannot be determined from the provided evidence'.
    Rejects hypotheses that assert specific rates/mechanisms not present in the contract rules or events.
    """
    present_rule_types = {r.get("rule_type") for r in (contract_rules or []) if r.get("rule_type")}
    FALLBACK_CAUSE = "Cause cannot be determined from the provided evidence"
    grounded = []

    for hyp in possible_explanations or []:
        hyp_str = str(hyp).strip()
        if not hyp_str:
            continue
        if hyp_str == FALLBACK_CAUSE:
            if FALLBACK_CAUSE not in grounded:
                grounded.append(FALLBACK_CAUSE)
            continue

        is_ungrounded = False
        for rule_type, patterns in MECHANISM_PATTERNS.items():
            if rule_type not in present_rule_types:
                for pat in patterns:
                    if pat.search(hyp_str):
                        logger.warning(
                            "Rejected ungrounded hypothesis asserting '%s' mechanism not in contract rules: %s",
                            rule_type,
                            hyp_str,
                        )
                        is_ungrounded = True
                        break
            if is_ungrounded:
                break

        if is_ungrounded:
            if FALLBACK_CAUSE not in grounded:
                grounded.append(FALLBACK_CAUSE)
        else:
            grounded.append(hyp_str)

    if not grounded:
        grounded.append(FALLBACK_CAUSE)

    return grounded


WORD_NUMS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
MULTIPLIERS = {
    "hundred": 100,
    "thousand": 1000,
    "million": 1000000,
}


def parse_words_to_number(words_str: str) -> Optional[int]:
    """Parses written-out words into a single integer (e.g. 'five thousand' -> 5000)."""
    tokens = re.findall(r"[a-zA-Z]+|[0-9]+", words_str.lower())
    if not tokens:
        return None
    total = 0
    current = 0
    for w in tokens:
        if w in WORD_NUMS:
            current += WORD_NUMS[w]
        elif w.isdigit():
            current += int(w)
        elif w in MULTIPLIERS:
            mult = MULTIPLIERS[w]
            if current == 0:
                current = 1
            if mult >= 1000:
                total += current * mult
                current = 0
            else:
                current *= mult
        elif w == "and":
            continue
        else:
            return None
    return total + current


def extract_monetary_amounts_cents(text: str) -> list[tuple[str, int, bool]]:
    """
    Quality Gate (Task 5c): Extracts explicit monetary amounts from narrative text:
      - Dollar, Euro, Pound symbols ($X, €X, £X)
      - Currency code prefixes (EUR 5000, USD 5000, GBP 5000)
      - Currency suffixes (5,000 USD, 5000 EUR, 5000 GBP, 5000 dollars, 5000 euros, 5000 pounds)
      - Cents (5000¢, 5000 cents, 5000c)
      - Written-out numbers ("five thousand dollars", "fifty dollars", "one hundred euros")
    Returns list of (raw_token, amount_cents, is_rate).
    """
    if not text:
        return []
    results = []
    seen_tokens = set()

    def add_result(raw_str: str, cents: int, is_rate: bool):
        key = (raw_str, cents, is_rate)
        if key not in seen_tokens:
            seen_tokens.add(key)
            results.append((raw_str, cents, is_rate))

    # 1. Prefix: $, €, £, or EUR/USD/GBP followed by number
    prefix_matches = re.finditer(
        r"(?:\$|€|£|\b(?:EUR|USD|GBP)\s*)([0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)(\s*(?:/|per\s+)[a-zA-Z]+)?",
        text,
        re.IGNORECASE,
    )
    for m in prefix_matches:
        raw_str = m.group(0).strip()
        num_str = m.group(1).replace(",", "")
        is_rate = bool(m.group(2))
        try:
            val_cents = int((Decimal(num_str) * 100).to_integral_value())
            add_result(raw_str, val_cents, is_rate)
        except (InvalidOperation, TypeError, ValueError) as exc:
            logger.debug("Currency prefix parse skipped for %r: %s", raw_str, exc)

    # 2. Suffix: 5,000 USD, 5000 USD, 5000 EUR, 5000 GBP, 5000 dollars, 5000 euros, 5000 pounds
    suffix_matches = re.finditer(
        r"(?<![0-9\$€£])([0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)\s*(?:USD|EUR|GBP|dollars?|euros?|pounds?)(\s*(?:/|per\s+)[a-zA-Z]+)?\b",
        text,
        re.IGNORECASE,
    )
    for m in suffix_matches:
        raw_str = m.group(0).strip()
        num_str = m.group(1).replace(",", "")
        is_rate = bool(m.group(2))
        try:
            val_cents = int((Decimal(num_str) * 100).to_integral_value())
            add_result(raw_str, val_cents, is_rate)
        except (InvalidOperation, TypeError, ValueError) as exc:
            logger.debug("Currency suffix parse skipped for %r: %s", raw_str, exc)

    # 3. Cents / pence: 5000¢, 5000 cents, 5000c
    cent_matches = re.finditer(
        r"(?<![0-9])([0-9]+)\s*(?:¢|cents?|pence|c)(?!\w)",
        text,
        re.IGNORECASE,
    )
    for m in cent_matches:
        raw_str = m.group(0).strip()
        num_str = m.group(1)
        is_rate = False
        try:
            val_cents = int(num_str)
            add_result(raw_str, val_cents, is_rate)
        except (InvalidOperation, TypeError, ValueError) as exc:
            logger.debug("Cent parse skipped for %r: %s", raw_str, exc)

    # 4. Written-out numbers: "five thousand dollars", "fifty dollars", "one hundred euros", "5 thousand USD"
    written_matches = re.finditer(
        r"\b((?:(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|and|[0-9]+)[\s-]+)+)\s*(dollars?|usd|euros?|eur|pounds?|gbp|cents?|pence)\b",
        text,
        re.IGNORECASE,
    )
    for m in written_matches:
        raw_str = m.group(0).strip()
        words = m.group(1).strip()
        unit = m.group(2).lower()
        val = parse_words_to_number(words)
        if val is not None:
            if unit in ("cents", "cent", "pence"):
                val_cents = val
            else:
                val_cents = val * 100
            add_result(raw_str, val_cents, False)

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

    # Allow grounded net recovery cap amounts: gross discrepancy minus verified adjustments
    total_verified_adj = sum(
        adj.get("amount_cents", 0)
        for adj in (adjustments or [])
        if adj.get("is_verified") is not False
    )
    for lr in line_results:
        diff = lr.get("difference_cents")
        if diff is not None and diff < 0:
            gross = abs(diff)
            allowed_cents.add(max(0, gross - total_verified_adj))
            for adj in (adjustments or []):
                if adj.get("is_verified") is not False and adj.get("amount_cents") is not None:
                    allowed_cents.add(max(0, gross - adj["amount_cents"]))

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
            if summary["total_difference_cents"] < 0:
                allowed_cents.add(max(0, abs(summary["total_difference_cents"]) - total_verified_adj))

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

