"""
agent/llm_client.py
===================
Wrapper for Gemini LLM calls via the official google-genai SDK,
with a deterministic mock mode for offline testing and CI.
"""

import json
import logging
import re
import time
from typing import Any, Optional

from app.agent.prompts import (
    FINDING_ANALYSIS_SYSTEM_INSTRUCTION,
    RESOLUTION_OPTIONS_SYSTEM_INSTRUCTION,
    build_analysis_prompt,
    build_resolution_options_prompt,
)
from app.agent.providers import classify_error, get_provider
from app.config import settings
from app.logging import log_llm_execution

logger = logging.getLogger(__name__)


def sanitize_error_message(text: str) -> str:
    """Strips API keys, bearer tokens, and secrets from error text."""
    if not text:
        return ""
    # Strip any configured keys and tokens
    for key in (
        settings.gemini_api_key,
        settings.groq_api_key,
        settings.openrouter_api_key,
        settings.demo_reviewer_token,
        settings.demo_viewer_token,
    ):
        if key and len(key) > 5 and not key.startswith("your-") and not key.startswith("your_"):
            text = text.replace(key, "[REDACTED_API_KEY]")
    # Redact common key prefixes and formats
    text = re.sub(r"gsk_[A-Za-z0-9_-]+", "[REDACTED_GROQ_KEY]", text)
    text = re.sub(r"sk-or-v1-[A-Za-z0-9_-]+", "[REDACTED_OPENROUTER_KEY]", text)
    text = re.sub(r"AIza[0-9A-Za-z-_]{35}", "[REDACTED_GEMINI_KEY]", text)
    text = re.sub(r"AQ\.[A-Za-z0-9_-]+", "[REDACTED_GEMINI_KEY]", text)
    text = re.sub(r"Bearer\s+[A-Za-z0-9_\-\.]+", "Bearer [REDACTED]", text, flags=re.IGNORECASE)
    return text


class AllProvidersFailedError(RuntimeError):
    """Raised when all configured LLM providers fail or are exhausted."""

    def __init__(self, message: str, attempts: Optional[list[dict[str, Any]]] = None):
        sanitized = sanitize_error_message(message)
        super().__init__(sanitized)
        self.attempts = attempts or []


def _clean_json_markdown(text: str) -> str:
    """Strips markdown code fences (```json ... ```) if returned by LLM."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _mock_analysis(prompt: str, state: dict[str, Any], target_lr: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Generates deterministic mock finding analysis from state, anchored to target_lr when specified."""
    line_results = state.get("line_results", [])
    calc_status = state.get("calculation_status", "OK")

    if target_lr is None:
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
    else:
        primary_lr = target_lr

    citation_id = primary_lr.get("result_id", "res_unknown")
    lr_db_id = primary_lr.get("id")
    target_line_id = primary_lr.get("line_id", "unknown")
    matching_rules = [r.get("id") for r in state.get("contract_rules", []) if r.get("line_id") == target_line_id]

    c_ids = [citation_id]
    if target_line_id and target_line_id != "unknown":
        c_ids.append(target_line_id)
    if matching_rules:
        c_ids.extend(matching_rules)

    lr_finding = primary_lr.get("finding_type")

    if lr_finding == "AMBIGUOUS" or (target_lr is None and calc_status == "AMBIGUOUS"):
        return {
            "finding_type": "CONTRACT_AMBIGUITY",
            "summary_narrative": (
                f"The contract terms on line '{target_line_id}' allow multiple valid pricing interpretations. "
                "The deterministic engine identified competing interpretations (graduated vs volume tiers)."
            ),
            "verified_facts": [
                f"Line item '{target_line_id}' was billed {primary_lr.get('original_amount_cents')}¢.",
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
            "calculation_line_result_id": lr_db_id,
        }

    if lr_finding == "INSUFFICIENT_DATA" or (target_lr is None and calc_status == "INSUFFICIENT_DATA"):
        return {
            "finding_type": "INSUFFICIENT_EVIDENCE",
            "summary_narrative": (
                f"Insufficient evidence available to complete recalculation on line '{target_line_id}'. "
                f"Engine reported: {primary_lr.get('explanation') or state.get('calculation_status_reason', 'Missing usage data or contract rules')}."
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
            "calculation_line_result_id": lr_db_id,
        }

    diff_cents = primary_lr.get("difference_cents", 0)
    if diff_cents < 0:
        orig_cents = primary_lr.get("original_amount_cents", 0)
        recalc_cents = primary_lr.get("recalculated_amount_cents", 0)
        return {
            "finding_type": "CONFIRMED_CALCULATION_DISCREPANCY",
            "summary_narrative": (
                f"Deterministic billing recalculation confirms customer was overcharged on line '{target_line_id}'. "
                f"Original billed: {orig_cents}¢; recalculated per contract rule: {recalc_cents}¢; "
                f"discrepancy: {diff_cents}¢."
            ),
            "verified_facts": [
                f"Customer was billed {orig_cents}¢ for line '{target_line_id}'.",
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
            "citation_ids": c_ids,
            "calculation_line_result_id": lr_db_id,
        }

    # No discrepancy
    return {
        "finding_type": "NO_DISCREPANCY",
        "summary_narrative": (
            f"Deterministic engine recalculation for line '{target_line_id}' matches the original billed amounts exactly. "
            "No calculation error or rule violation was detected."
        ),
        "verified_facts": [
            f"Line '{target_line_id}' recalculates identically to the billed amounts.",
        ],
        "possible_explanations": [
            "Customer may have misunderstood contract tier boundaries or minimum commit terms.",
        ],
        "assumptions": [
            "Contract rules and usage logs are complete.",
        ],
        "open_questions": [],
        "missing_evidence_questions": [],
        "citation_ids": c_ids if citation_id != "res_unknown" else [],
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
        options = []
        target_lr = next((lr for lr in state.get("line_results", []) if lr.get("id") == lr_id), None)
        undisputed_amt = target_lr.get("undisputed_overcharge_cents") if target_lr else None
        if target_lr and undisputed_amt and undisputed_amt > 0:
            options.append({
                "option_type": "CREDIT_UNDISPUTED_PORTION",
                "description": (
                    f"Credit undisputed minimum overcharge of {undisputed_amt}¢ under every contract interpretation. "
                    "Remainder awaits contract clarification."
                ),
                "calculation_line_result_id": lr_id,
            })
        options.append({
            "option_type": "ESCALATE",
            "description": (
                "Escalate to billing operations or legal counsel to determine the legally binding interpretation "
                "for the disputed tiered contract clause."
            ),
            "calculation_line_result_id": lr_id,
        })
        return options

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
    **kwargs,
) -> tuple[str, dict[str, Any]]:
    """
    Invokes LLM providers in fallback order (Gemini -> Groq -> OpenRouter)
    with automatic retries on 429/5xx/timeout and immediate failover on 401/403/404.
    Returns (raw_response_text, token_usage_dict_with_meta).
    Never mocks or fabricates output when LLM_MODE=real.
    """
    run_id = kwargs.get("run_id")
    if settings.llm_mode == "mock":
        return ("", {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "provider": "mock",
            "model": "mock-deterministic",
            "attempts": [],
        })

    provider_names = [p.strip().lower() for p in settings.llm_providers.split(",") if p.strip()]
    attempts: list[dict[str, Any]] = []
    failed_reasons: list[tuple[str, str]] = []

    total_start_time = time.time()
    max_total_timeout = 40.0

    for p_name in provider_names:
        elapsed = time.time() - total_start_time
        if elapsed >= max_total_timeout:
            raise TimeoutError(f"Total LLM execution deadline exceeded ({max_total_timeout}s)")

        try:
            provider = get_provider(p_name)
        except Exception as e:
            logger.warning("Could not instantiate provider %s: %s", p_name, sanitize_error_message(str(e)))
            continue

        if not provider.is_configured:
            # Check if key is present but model is missing
            key_val = getattr(provider, "_api_key", "")
            model_val = getattr(provider, "_model", "")
            if key_val and not model_val:
                msg = f"{p_name.upper()}_API_KEY is configured but {p_name.upper()}_MODEL is missing"
                attempts.append({"provider": p_name, "error_type": "MISSING_MODEL"})
                failed_reasons.append((p_name, msg))
                logger.warning("Provider %s skipped: %s", p_name, msg)
            continue

        # Attempt 1
        elapsed = time.time() - total_start_time
        remaining = max_total_timeout - elapsed
        if remaining <= 0:
            raise TimeoutError(f"Total LLM execution deadline exceeded ({max_total_timeout}s)")

        call_timeout = min(timeout_sec, max(1.0, remaining))
        t0 = time.perf_counter()
        try:
            raw_text, tokens, prov_name, model_name = provider.generate_json(
                system_instruction=system_instruction,
                prompt=prompt,
                timeout_sec=int(call_timeout),
            )
            cleaned = _clean_json_markdown(raw_text)
            json.loads(cleaned)
            latency_ms = (time.perf_counter() - t0) * 1000
            log_llm_execution(
                run_id=run_id,
                provider=prov_name,
                model=model_name,
                attempt=1,
                latency_ms=latency_ms,
                status="SUCCESS",
                tokens=tokens,
            )
            tokens_result = dict(tokens)
            tokens_result["provider"] = prov_name
            tokens_result["model"] = model_name
            tokens_result["attempts"] = list(attempts)
            return (cleaned, tokens_result)
        except Exception as e:
            latency_ms = (time.perf_counter() - t0) * 1000
            error_type, should_retry = classify_error(e)
            sanitized_err = sanitize_error_message(str(e))
            log_llm_execution(
                run_id=run_id,
                provider=provider.name,
                model=provider.model,
                attempt=1,
                latency_ms=latency_ms,
                status="FAILED",
                error_type=error_type,
            )
            attempts.append({"provider": provider.name, "error_type": error_type})

            if not should_retry:
                failed_reasons.append((provider.name, f"{error_type}: {sanitized_err}"))
                logger.warning(
                    "Provider %s (%s) failed with non-retryable error %s: %s",
                    provider.name,
                    provider.model,
                    error_type,
                    sanitized_err,
                )
                continue

            # Retry once after 1s for 429, 5xx, or timeout
            logger.info("Provider %s encountered %s; retrying once after 1s...", provider.name, error_type)
            time.sleep(1)

            elapsed = time.time() - total_start_time
            remaining = max_total_timeout - elapsed
            if remaining <= 0:
                raise TimeoutError(f"Total LLM execution deadline exceeded ({max_total_timeout}s)")

            call_timeout2 = min(timeout_sec, max(1.0, remaining))
            t1 = time.perf_counter()
            try:
                raw_text, tokens, prov_name, model_name = provider.generate_json(
                    system_instruction=system_instruction,
                    prompt=prompt,
                    timeout_sec=int(call_timeout2),
                )
                cleaned = _clean_json_markdown(raw_text)
                json.loads(cleaned)
                latency_ms = (time.perf_counter() - t1) * 1000
                log_llm_execution(
                    run_id=run_id,
                    provider=prov_name,
                    model=model_name,
                    attempt=2,
                    latency_ms=latency_ms,
                    status="SUCCESS",
                    tokens=tokens,
                )
                tokens_result = dict(tokens)
                tokens_result["provider"] = prov_name
                tokens_result["model"] = model_name
                tokens_result["attempts"] = list(attempts)
                return (cleaned, tokens_result)
            except Exception as e2:
                latency_ms = (time.perf_counter() - t1) * 1000
                error_type2, _ = classify_error(e2)
                sanitized_err2 = sanitize_error_message(str(e2))
                log_llm_execution(
                    run_id=run_id,
                    provider=provider.name,
                    model=provider.model,
                    attempt=2,
                    latency_ms=latency_ms,
                    status="FAILED",
                    error_type=error_type2,
                )
                attempts.append({"provider": provider.name, "error_type": error_type2})
                failed_reasons.append((provider.name, f"{error_type2}: {sanitized_err2}"))
                continue

    err_details = "; ".join(f"{p}: {r}" for p, r in failed_reasons) if failed_reasons else "No enabled LLM providers configured"
    raise AllProvidersFailedError(f"All LLM providers failed: {err_details}", attempts=attempts)


def generate_investigation_findings(
    state: dict[str, Any],
    target_lr: Optional[dict[str, Any]] = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Analyzes evidence and deterministic calculation to produce findings for a target line or overall."""
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
        usage_events=state.get("usage_events", []),
        adjustments=state.get("adjustments", []),
        quarantined_events=state.get("quarantined_events", []),
    )
    if target_lr:
        prompt += (
            f"\nTARGET INVOICE LINE FOR THIS FINDING:\n"
            f"Focus your finding specifically on line '{target_lr.get('line_id')}' (DB ID: {target_lr.get('id')}, Result ID: {target_lr.get('result_id')}). "
            f"Set calculation_line_result_id to {target_lr.get('id')}.\n"
        )

    if settings.llm_mode == "mock":
        data = _mock_analysis(prompt, state, target_lr=target_lr)
        data["generation_path"] = "mock"
        tokens = {
            "prompt_tokens": 120,
            "completion_tokens": 85,
            "total_tokens": 205,
            "provider": "mock",
            "model": "mock-deterministic",
            "attempts": [],
        }
        return data, tokens

    try:
        raw_text, tokens = call_llm(
            prompt,
            FINDING_ANALYSIS_SYSTEM_INSTRUCTION,
        )
        cleaned = _clean_json_markdown(raw_text)
        parsed = json.loads(cleaned)
        parsed["generation_path"] = "llm"
        return parsed, tokens
    except AllProvidersFailedError:
        raise
    except Exception as e:
        logger.error("Error in real LLM findings call: %s", sanitize_error_message(str(e)))
        raise AllProvidersFailedError(
            f"Live LLM call failed: {sanitize_error_message(str(e))}; refusing to fake AI analysis",
            attempts=[],
        )


def generate_resolution_options(
    state: dict[str, Any],
    finding: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Formulates resolution options based on confirmed findings."""
    prompt = build_resolution_options_prompt(
        finding_type=finding.get("finding_type", "UNRESOLVED"),
        summary_narrative=finding.get("summary_narrative", ""),
        line_results=state.get("line_results", []),
    )

    if settings.llm_mode == "mock":
        tokens = {
            "prompt_tokens": 80,
            "completion_tokens": 45,
            "total_tokens": 125,
            "provider": "mock",
            "model": "mock-deterministic",
            "attempts": [],
        }
        return _mock_options(prompt, finding, state), tokens

    try:
        raw_text, tokens = call_llm(
            prompt,
            RESOLUTION_OPTIONS_SYSTEM_INSTRUCTION,
        )
        cleaned = _clean_json_markdown(raw_text)
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict) and "options" in parsed:
            parsed = parsed["options"]
        if not isinstance(parsed, list):
            parsed = [parsed]
        return parsed, tokens
    except AllProvidersFailedError:
        raise
    except Exception as e:
        logger.error("Error in real LLM options call: %s", sanitize_error_message(str(e)))
        raise AllProvidersFailedError(
            f"Live LLM options call failed: {sanitize_error_message(str(e))}; refusing to fake AI options",
            attempts=[],
        )
