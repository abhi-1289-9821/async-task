"""
agent/llm_client.py
===================
Wrapper for Gemini LLM calls via the official google-genai SDK,
with a deterministic mock mode for offline testing and CI.
"""

import json
import logging
import re
from typing import Any, Optional

from app.agent.prompts import (
    FINDING_ANALYSIS_SYSTEM_INSTRUCTION,
    RESOLUTION_OPTIONS_SYSTEM_INSTRUCTION,
    build_analysis_prompt,
    build_resolution_options_prompt,
)
from app.config import settings

logger = logging.getLogger(__name__)


def _clean_json_markdown(text: str) -> str:
    """Strips markdown code fences (```json ... ```) if returned by LLM."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _mock_analysis(prompt: str, state: dict[str, Any]) -> dict[str, Any]:
    """Generates deterministic mock finding analysis from state."""
    line_results = state.get("line_results", [])
    calc_status = state.get("calculation_status", "OK")

    # Check for discrepancy, ambiguity, or missing data
    ambiguous_lrs = [lr for lr in line_results if lr.get("finding_type") == "AMBIGUOUS"]
    insufficient_lrs = [lr for lr in line_results if lr.get("finding_type") == "INSUFFICIENT_DATA"]
    overcharged = [lr for lr in line_results if lr.get("difference_cents", 0) < 0]

    primary_lr = (
        ambiguous_lrs[0] if ambiguous_lrs else (
            insufficient_lrs[0] if insufficient_lrs else (
                overcharged[0] if overcharged else (line_results[0] if line_results else {})
            )
        )
    )
    citation_id = primary_lr.get("result_id", "res_unknown")
    lr_db_id = primary_lr.get("id")

    if calc_status == "AMBIGUOUS":
        target_amb = ambiguous_lrs[0] if ambiguous_lrs else primary_lr
        c_ids = [lr.get("result_id") for lr in ambiguous_lrs if lr.get("result_id")] or [citation_id]
        return {
            "finding_type": "CONTRACT_AMBIGUITY",
            "summary_narrative": (
                f"The contract terms on line '{target_amb.get('line_id')}' allow multiple valid pricing interpretations. "
                "The deterministic engine identified competing interpretations (graduated vs volume tiers)."
            ),
            "verified_facts": [
                f"Line item '{target_amb.get('line_id')}' was billed {target_amb.get('original_amount_cents')}¢.",
                "Contract rule contains ambiguous tier boundaries.",
            ],
            "possible_explanations": [
                "Contract amendment may not have specified graduated vs volume pricing.",
            ],
            "assumptions": [
                "Assumed both tiered models are plausible based on contract language.",
            ],
            "open_questions": [
                "Which interpretation was mutually agreed upon in the order form?",
            ],
            "missing_evidence_questions": [
                "Order form amendment detailing tier calculation method.",
            ],
            "citation_ids": c_ids,
            "calculation_line_result_id": target_amb.get("id"),
        }

    if calc_status == "INSUFFICIENT_DATA":
        target_ins = insufficient_lrs[0] if insufficient_lrs else primary_lr
        c_ids = [lr.get("result_id") for lr in insufficient_lrs if lr.get("result_id")] or [citation_id]
        return {
            "finding_type": "INSUFFICIENT_EVIDENCE",
            "summary_narrative": (
                f"Insufficient evidence available to complete recalculation on line '{target_ins.get('line_id')}'. "
                f"Engine reported: {state.get('calculation_status_reason', 'Missing usage data or contract rules')}."
            ),
            "verified_facts": [
                "Dispute was filed by customer.",
            ],
            "possible_explanations": [
                "Usage telemetry ingestion failed for the billing period.",
            ],
            "assumptions": [],
            "open_questions": [
                "Are there missing usage log batches from staging or production?",
            ],
            "missing_evidence_questions": [
                "Complete usage event logs for the disputed period.",
            ],
            "citation_ids": c_ids,
            "calculation_line_result_id": target_ins.get("id"),
        }

    # Check for overcharge in line results
    if overcharged:
        target = overcharged[0]
        diff_cents = target.get("difference_cents", 0)
        orig_cents = target.get("original_amount_cents", 0)
        recalc_cents = target.get("recalculated_amount_cents", 0)
        return {
            "finding_type": "CONFIRMED_CALCULATION_DISCREPANCY",
            "summary_narrative": (
                f"Deterministic billing recalculation confirms customer was overcharged on line '{target.get('line_id')}'. "
                f"Original billed: {orig_cents}¢; recalculated per contract rule: {recalc_cents}¢; "
                f"discrepancy: {diff_cents}¢."
            ),
            "verified_facts": [
                f"Customer was billed {orig_cents}¢ for line '{target.get('line_id')}'.",
                f"Deterministic engine recalculation yields {recalc_cents}¢.",
                f"Overcharge discrepancy confirmed as {abs(diff_cents)}¢.",
            ],
            "possible_explanations": [
                "Incorrect pricing tier applied by billing batch job.",
                "Staging environment usage improperly included in billable usage.",
            ],
            "assumptions": [
                "Telemetry events provided in evidence are authoritative.",
            ],
            "open_questions": [],
            "missing_evidence_questions": [],
            "citation_ids": [target.get("result_id")],
            "calculation_line_result_id": target.get("id"),
        }

    # No discrepancy
    return {
        "finding_type": "NO_DISCREPANCY",
        "summary_narrative": (
            "Deterministic engine recalculation matches the original billed amounts exactly. "
            "No calculation error or rule violation was detected."
        ),
        "verified_facts": [
            "All invoice lines recalculate identically to the billed amounts.",
        ],
        "possible_explanations": [
            "Customer may have misunderstood contract tier boundaries or minimum commit terms.",
        ],
        "assumptions": [
            "Contract rules and usage logs are complete.",
        ],
        "open_questions": [],
        "missing_evidence_questions": [],
        "citation_ids": [citation_id] if citation_id != "res_unknown" else [],
        "calculation_line_result_id": lr_db_id,
    }


def _mock_options(prompt: str, finding: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    """Generates deterministic mock resolution options based on finding."""
    finding_type = finding.get("finding_type")
    lr_id = finding.get("calculation_line_result_id")

    if finding_type == "CONFIRMED_CALCULATION_DISCREPANCY" and lr_id is not None:
        return [
            {
                "option_type": "RECOMMEND_CREDIT",
                "description": (
                    "Approve a credit for the verified overcharge amount calculated by the deterministic engine. "
                    "Amount is anchored strictly to the calculation line result."
                ),
                "calculation_line_result_id": lr_id,
            },
            {
                "option_type": "CORRECT_INVOICE",
                "description": "Issue an amended invoice with the corrected usage and pricing tier applied.",
                "calculation_line_result_id": lr_id,
            },
        ]

    if finding_type == "CONTRACT_AMBIGUITY":
        return [
            {
                "option_type": "ESCALATE",
                "description": (
                    "Escalate to billing operations or legal counsel to determine the legally binding interpretation "
                    "for the disputed tiered contract clause."
                ),
                "calculation_line_result_id": lr_id,
            }
        ]

    if finding_type == "INSUFFICIENT_EVIDENCE":
        return [
            {
                "option_type": "REQUEST_EVIDENCE",
                "description": "Request missing usage telemetry or contract amendment documents from customer/account team.",
                "calculation_line_result_id": None,
            }
        ]

    return [
        {
            "option_type": "CLOSE_NO_ADJUSTMENT",
            "description": "Close dispute with no financial adjustment; provide calculation breakdown to customer.",
            "calculation_line_result_id": None,
        }
    ]


def call_llm(
    prompt: str,
    system_instruction: str,
    timeout_sec: int = 15,
) -> tuple[str, dict[str, int]]:
    """
    Invokes the Gemini LLM via google-genai or returns mock output.
    Returns (raw_response_text, token_usage_dict).
    """
    if settings.llm_mode == "mock" or not settings.gemini_api_key:
        return ("", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})

    from google import genai
    from google.genai import types

    # Candidate models: try configured model first, then fallback to current stable models
    configured_model = settings.gemini_model or "gemini-3.1-flash-lite"
    candidate_models = [configured_model]
    for fallback in ["gemini-3.1-flash-lite", "gemini-3.8-flash"]:
        if fallback not in candidate_models:
            candidate_models.append(fallback)

    last_err: Optional[Exception] = None
    client = genai.Client(
        api_key=settings.gemini_api_key,
        http_options=types.HttpOptions(timeout=timeout_sec * 1000),
    )
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
    )

    for model_name in candidate_models:
        for attempt in range(2):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=config,
                )

                tokens = {
                    "prompt_tokens": getattr(response.usage_metadata, "prompt_token_count", 0) if response.usage_metadata else 0,
                    "completion_tokens": getattr(response.usage_metadata, "candidates_token_count", 0) if response.usage_metadata else 0,
                    "total_tokens": getattr(response.usage_metadata, "total_token_count", 0) if response.usage_metadata else 0,
                }
                return (response.text or "", tokens)
            except Exception as e:
                logger.warning("Gemini LLM call (model=%s, attempt=%d) failed: %s", model_name, attempt + 1, e)
                last_err = e
                # If model is deprecated / not found (404), skip retrying this model and advance to next candidate immediately
                err_str = str(e)
                if "404" in err_str or "NOT_FOUND" in err_str:
                    break

    raise RuntimeError(f"Gemini LLM call failed across models {candidate_models}: {last_err}")


def generate_investigation_findings(state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    """Analyzes evidence and deterministic calculation to produce findings."""
    prompt = build_analysis_prompt(
        case_title=state.get("case_data", {}).get("title", ""),
        customer_name=state.get("case_data", {}).get("customer_name", ""),
        dispute_text=state.get("dispute_text", ""),
        invoice_lines=state.get("invoice_lines", []),
        contract_rules=state.get("contract_rules", []),
        calculation_summary={
            "engine_status": state.get("calculation_status"),
            "engine_status_reason": state.get("calculation_status_reason"),
            "total_original_billed_cents": state.get("total_original_billed_cents", 0),
            "total_recalculated_cents": state.get("total_recalculated_cents", 0),
            "total_difference_cents": state.get("total_difference_cents", 0),
        },
        line_results=state.get("line_results", []),
    )

    if settings.llm_mode == "mock":
        data = _mock_analysis(prompt, state)
        data["generation_path"] = "mock"
        return data, {"prompt_tokens": 120, "completion_tokens": 85, "total_tokens": 205}

    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured while LLM_MODE=real; refusing to fabricate mock findings in live mode")

    try:
        raw_text, tokens = call_llm(prompt, FINDING_ANALYSIS_SYSTEM_INSTRUCTION)
        cleaned = _clean_json_markdown(raw_text)
        parsed = json.loads(cleaned)
        parsed["generation_path"] = "llm"
        return parsed, tokens
    except Exception as e:
        logger.error("Error in real LLM findings call: %s", e)
        raise RuntimeError(f"Live Gemini LLM call failed: {e}; refusing to fake AI analysis")


def generate_resolution_options(
    state: dict[str, Any],
    finding: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Formulates resolution options based on confirmed findings."""
    prompt = build_resolution_options_prompt(
        finding_type=finding.get("finding_type", "UNRESOLVED"),
        summary_narrative=finding.get("summary_narrative", ""),
        line_results=state.get("line_results", []),
    )

    if settings.llm_mode == "mock":
        return _mock_options(prompt, finding, state), {"prompt_tokens": 80, "completion_tokens": 45, "total_tokens": 125}

    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured while LLM_MODE=real; refusing to fabricate mock options in live mode")

    try:
        raw_text, tokens = call_llm(prompt, RESOLUTION_OPTIONS_SYSTEM_INSTRUCTION)
        cleaned = _clean_json_markdown(raw_text)
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict) and "options" in parsed:
            parsed = parsed["options"]
        if not isinstance(parsed, list):
            parsed = [parsed]
        return parsed, tokens
    except Exception as e:
        logger.error("Error in real LLM options call: %s", e)
        raise RuntimeError(f"Live Gemini LLM options call failed: {e}; refusing to fake AI options")
