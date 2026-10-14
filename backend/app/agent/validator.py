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


def validate_consistency(
    finding: dict[str, Any],
    calculation_status: str,
    total_difference_cents: int,
    line_results: list[dict[str, Any]],
) -> tuple[bool, str, list[str]]:
    """
    Verifies that the finding type is mathematically consistent with the deterministic engine.
    If contradiction exists, returns (False, "UNRESOLVED", errors).
    """
    finding_type = finding.get("finding_type", "UNRESOLVED")
    errors = []

    # 1. Contradiction: AI claims discrepancy, but engine has 0 difference and OK status
    has_overcharge = any(lr.get("difference_cents", 0) < 0 for lr in line_results)
    if finding_type == "CONFIRMED_CALCULATION_DISCREPANCY":
        if not has_overcharge and total_difference_cents == 0:
            errors.append(
                "Contradiction: AI claimed CONFIRMED_CALCULATION_DISCREPANCY but deterministic engine found 0 difference"
            )
            return False, "UNRESOLVED", errors

    # 2. Contradiction: Engine found ambiguity, but AI claimed NO_DISCREPANCY
    if calculation_status == "AMBIGUOUS" and finding_type == "NO_DISCREPANCY":
        errors.append(
            "Contradiction: Engine reported AMBIGUOUS clauses, but AI claimed NO_DISCREPANCY"
        )
        return False, "CONTRACT_AMBIGUITY", errors

    # 3. Contradiction: Engine found missing data, but AI claimed NO_DISCREPANCY
    if calculation_status == "INSUFFICIENT_DATA" and finding_type == "NO_DISCREPANCY":
        errors.append(
            "Contradiction: Engine reported INSUFFICIENT_DATA, but AI claimed NO_DISCREPANCY"
        )
        return False, "INSUFFICIENT_EVIDENCE", errors

    return True, finding_type, []


def sanitize_resolution_options(
    options: list[dict[str, Any]],
    line_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Validates resolution options.
    For RECOMMEND_CREDIT, requires a valid line result with negative difference (overcharge).
    Ensures no financial amounts are accepted from LLM text.
    """
    line_results_by_id = {lr.get("id"): lr for lr in line_results if lr.get("id") is not None}
    sanitized: list[dict[str, Any]] = []

    for opt in options:
        opt_type = opt.get("option_type", "CLOSE_NO_ADJUSTMENT")
        description = opt.get("description", "")
        lr_id = opt.get("calculation_line_result_id")

        if opt_type == "RECOMMEND_CREDIT":
            # Must point to an existing line result with an overcharge
            lr = line_results_by_id.get(lr_id)
            if not lr or lr.get("difference_cents", 0) >= 0:
                logger.warning(
                    "Rejected RECOMMEND_CREDIT option: line_result_id %s has no overcharge (diff: %s)",
                    lr_id,
                    lr.get("difference_cents") if lr else "None",
                )
                continue
        elif lr_id not in line_results_by_id:
            lr_id = None

        sanitized.append({
            "option_type": opt_type,
            "description": description,
            "calculation_line_result_id": lr_id,
        })

    if not sanitized:
        sanitized.append({
            "option_type": "CLOSE_NO_ADJUSTMENT",
            "description": "Default closure: no valid credit recommendation could be verified.",
            "calculation_line_result_id": None,
        })

    return sanitized


import re
from decimal import Decimal


def extract_monetary_amounts_cents(text: str) -> list[tuple[str, int]]:
    """
    Extracts explicit dollar ($X or $X.YY) and cent (X¢, X cents) amounts from narrative text.
    Returns list of (raw_token, amount_cents).
    """
    if not text:
        return []
    results = []

    # Match $50, $50.00, $0.50, $1,000.00, $9,999.99 (with optional comma grouping)
    dollar_matches = re.finditer(r"\$([0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)", text)
    for m in dollar_matches:
        raw_str = m.group(0)
        num_str = m.group(1).replace(",", "")
        try:
            val_cents = int((Decimal(num_str) * 100).to_integral_value())
            results.append((raw_str, val_cents))
        except Exception:
            pass

    # Match 5000¢, 5000 cents, 5000 cent (handles punctuation like 5000¢. without \b failure on non-word ¢)
    cent_matches = re.finditer(r"(?<![0-9])([0-9]+)\s*(?:¢|cents?)(?![a-zA-Z0-9])", text, re.IGNORECASE)
    for m in cent_matches:
        raw_str = m.group(0).strip()
        num_str = m.group(1)
        try:
            val_cents = int(num_str)
            results.append((raw_str, val_cents))
        except Exception:
            pass

    return results


def validate_narrative_amounts(
    finding: dict[str, Any],
    line_results: list[dict[str, Any]],
    summary: dict[str, Any],
) -> tuple[bool, list[str]]:
    """
    Scans AI finding narrative, facts, and explanations for fabricated dollar amounts.
    All monetary values mentioned in the text must be anchored to numbers emitted
    by the deterministic billing engine.
    """
    # Allow 0 and numbers calculated by deterministic engine
    allowed_cents = {0}
    for lr in line_results:
        allowed_cents.add(lr.get("original_amount_cents", 0))
        allowed_cents.add(lr.get("recalculated_amount_cents", 0))
        allowed_cents.add(abs(lr.get("difference_cents", 0)))
        if lr.get("applied_minimum_commit_cents"):
            allowed_cents.add(lr["applied_minimum_commit_cents"])

    if summary:
        allowed_cents.add(summary.get("total_original_billed_cents", 0))
        allowed_cents.add(summary.get("total_recalculated_cents", 0))
        allowed_cents.add(abs(summary.get("total_difference_cents", 0)))

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
        for raw_token, cents in extracted:
            if cents not in allowed_cents:
                unanchored.append(
                    f"Fabricated monetary amount '{raw_token}' ({cents}¢) detected in AI narrative; not anchored to engine calculation"
                )

    passed = (len(unanchored) == 0)
    return passed, unanchored

