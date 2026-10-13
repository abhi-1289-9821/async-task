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
    primary_lr = line_results[0] if line_results else {}
    citation_id = primary_lr.get("result_id", "res_unknown")
    lr_db_id = primary_lr.get("id")

    if calc_status == "AMBIGUOUS":
        return {
            "finding_type": "CONTRACT_AMBIGUITY",
            "summary_narrative": (
                "The contract terms allow multiple valid pricing interpretations for this line item. "
                "The deterministic engine identified competing interpretations (graduated vs volume tiers)."
            ),
            "verified_facts": [
                f"Line item '{primary_lr.get('line_id')}' was billed {primary_lr.get('original_amount_cents')}¢.",
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
            "citation_ids": [citation_id],
            "calculation_line_result_id": lr_db_id,
        }

    if calc_status == "INSUFFICIENT_DATA":
        return {
            "finding_type": "INSUFFICIENT_EVIDENCE",
            "summary_narrative": (
                "Insufficient evidence available to complete recalculation. "
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
            "citation_ids": [citation_id] if citation_id != "res_unknown" else [],
            "calculation_line_result_id": lr_db_id,
        }

    # Check for overcharge in line results
    overcharged = [lr for lr in line_results if lr.get("difference_cents", 0) < 0]
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

    # Bounded retries (max 2 attempts)
    last_err: Optional[Exception] = None
    for attempt in range(2):
        try:
            client = genai.Client(
                api_key=settings.gemini_api_key,
                http_options=types.HttpOptions(timeout=timeout_sec * 1000),
            )
            config = types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
            )
            model_name = settings.gemini_model or "gemini-3.8-flash"
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
            logger.warning("Gemini LLM call attempt %d failed: %s", attempt + 1, e)
            last_err = e

    raise RuntimeError(f"Gemini LLM call failed after 2 attempts: {last_err}")


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
        logger.warning("GEMINI_API_KEY is not set while LLM_MODE=real; falling back to deterministic mock")
        data = _mock_analysis(prompt, state)
        data["generation_path"] = "fallback_mock"
        return data, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    try:
        raw_text, tokens = call_llm(prompt, FINDING_ANALYSIS_SYSTEM_INSTRUCTION)
        cleaned = _clean_json_markdown(raw_text)
        parsed = json.loads(cleaned)
        parsed["generation_path"] = "llm"
        return parsed, tokens
    except Exception as e:
        logger.error("Error in real LLM findings call, falling back to deterministic mock: %s", e)
        # Graceful fallback to deterministic mock so system remains resilient
        mock_data = _mock_analysis(prompt, state)
        mock_data["generation_path"] = "fallback_mock"
        return mock_data, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


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

    if settings.llm_mode == "mock" or not settings.gemini_api_key:
        return _mock_options(prompt, finding, state), {"prompt_tokens": 80, "completion_tokens": 45, "total_tokens": 125}

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
        logger.error("Error in real LLM options call, falling back to deterministic mock: %s", e)
        mock_opts = _mock_options(prompt, finding, state)
        return mock_opts, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
