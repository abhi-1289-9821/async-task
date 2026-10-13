"""
agent/state.py
==============
TypedDict state definition for the LangGraph investigation workflow.
State flows immutably through each node in the StateGraph.
"""

from typing import Any, Optional, TypedDict


class AgentState(TypedDict, total=False):
    # Case & Execution Context
    case_id: str
    run_id: str
    actor: str
    correlation_id: Optional[str]
    evidence_version: int

    # Overall Run Status: RUNNING, COMPLETED, PARTIAL, FAILED, BLOCKED, DISCARDED
    status: str
    status_reason: Optional[str]

    # Gathered Evidence
    case_data: dict[str, Any]
    invoice_lines: list[dict[str, Any]]
    contract_rules: list[dict[str, Any]]
    usage_events: list[dict[str, Any]]
    adjustments: list[dict[str, Any]]
    dispute_text: str

    # Deterministic Engine Results
    calculation_id: Optional[str]
    calculation_status: Optional[str]
    calculation_status_reason: Optional[str]
    total_original_billed_cents: int
    total_recalculated_cents: int
    total_difference_cents: int
    result_hash: Optional[str]
    line_results: list[dict[str, Any]]
    valid_result_ids: list[str]

    # AI Outputs
    raw_findings: list[dict[str, Any]]
    raw_options: list[dict[str, Any]]

    # Validated Outputs
    validated_findings: list[dict[str, Any]]
    validated_options: list[dict[str, Any]]

    # Telemetry
    token_usage: dict[str, int]
    errors: list[str]
    warnings: list[str]
