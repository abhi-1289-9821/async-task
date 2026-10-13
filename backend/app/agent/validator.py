"""
agent/validator.py
==================
Rigorous verification layer enforcing:
1. Citation Integrity: all cited result IDs must strictly exist in the engine calculation.
2. Financial Consistency: finding type must not contradict deterministic math.
3. Option Validity: credit recommendations must anchor to real overcharged line results.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def validate_citations(
    finding: dict[str, Any],
    valid_result_ids: list[str],
) -> tuple[bool, list[str], list[str]]:
    """
    Validates that all citation_ids in the finding match existing engine result_ids.
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
            errors.append(f"Invalid citation ID '{c_str}'; not found in calculation line results")

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
