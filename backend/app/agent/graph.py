"""
agent/graph.py
==============
LangGraph StateGraph implementation for autonomous billing dispute investigations.
Enforces deterministic gates:
- Missing evidence blocks execution before finding creation (status = BLOCKED).
- Mathematical calculations are strictly delegated to the deterministic billing engine.
- Citations and amounts are strictly verified against calculation line results.
"""

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from app.agent import llm_client, validator
from app.agent.state import AgentState
from app.logging import log_agent_node_execution
from app.models.calculation import Calculation
from app.models.case import Case, CaseEvent
from app.models.invoice import ContractRule, InvoiceLine
from app.models.usage import UsageEvent
from app.models.credit import Adjustment
from app.models.investigation import (
    AgentFindingType,
    Finding,
    InvestigationRun,
    OptionType,
    ResolutionOption,
    RunStatus,
)
from app.services.calculation_service import execute_case_calculation


class InvestigationWorkflow:
    """Manages compilation and execution of the investigation StateGraph."""

    def __init__(self, db: Session):
        self.db = db
        self.graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(AgentState)

        # Nodes
        builder.add_node("gather_evidence", self.gather_evidence_node)
        builder.add_node("run_calculation", self.run_calculation_node)
        builder.add_node("analyze_findings", self.analyze_findings_node)
        builder.add_node("formulate_options", self.formulate_options_node)
        builder.add_node("validate_and_sanitize", self.validate_and_sanitize_node)
        builder.add_node("persist_results", self.persist_results_node)

        # Edges
        builder.add_edge(START, "gather_evidence")

        # Conditional route from gather_evidence:
        builder.add_conditional_edges(
            "gather_evidence",
            self.route_after_evidence,
            {
                "blocked": "persist_results",
                "continue": "run_calculation",
            },
        )

        builder.add_edge("run_calculation", "analyze_findings")
        builder.add_edge("analyze_findings", "formulate_options")
        builder.add_edge("formulate_options", "validate_and_sanitize")
        builder.add_edge("validate_and_sanitize", "persist_results")
        builder.add_edge("persist_results", END)

        return builder.compile()

    # ── Routing ───────────────────────────────────────────────────────────────
    @staticmethod
    def route_after_evidence(state: AgentState) -> str:
        if state.get("status") in ("BLOCKED", "FAILED"):
            return "blocked"
        return "continue"

    # ── Nodes ─────────────────────────────────────────────────────────────────
    def gather_evidence_node(self, state: AgentState) -> dict[str, Any]:
        """Loads all evidence from DB. If required data is missing, marks BLOCKED."""
        start_t = time.perf_counter()
        case_id = state["case_id"]
        case = self.db.query(Case).filter(Case.id == case_id).one_or_none()
        if not case:
            log_agent_node_execution(
                run_id=state["run_id"],
                case_id=case_id,
                node="gather_evidence",
                latency_ms=(time.perf_counter() - start_t) * 1000,
                status="FAILED",
            )
            return {
                "status": "FAILED",
                "status_reason": f"Case '{case_id}' not found",
            }

        lines = self.db.query(InvoiceLine).filter(InvoiceLine.case_id == case_id).all()
        rules = self.db.query(ContractRule).filter(ContractRule.case_id == case_id, ContractRule.is_active == True).all()
        events = self.db.query(UsageEvent).filter(UsageEvent.case_id == case_id).all()
        adjustments = self.db.query(Adjustment).filter(Adjustment.case_id == case_id).all()

        # Gate: If no invoice lines or no contract rules, cannot calculate
        if not lines or not rules:
            log_agent_node_execution(
                run_id=state["run_id"],
                case_id=case_id,
                node="gather_evidence",
                latency_ms=(time.perf_counter() - start_t) * 1000,
                status="BLOCKED",
            )
            return {
                "status": "BLOCKED",
                "status_reason": "MISSING_EVIDENCE: Case requires both invoice lines and contract rules to investigate",
                "evidence_version": case.evidence_version,
                "case_data": {
                    "id": case.id,
                    "title": case.title,
                    "customer_name": case.customer_name,
                    "disputed_amount_cents": case.disputed_amount_cents,
                },
                "dispute_text": case.title,
                "invoice_lines": [],
                "contract_rules": [],
                "usage_events": [],
                "adjustments": [],
            }

        log_agent_node_execution(
            run_id=state["run_id"],
            case_id=case_id,
            node="gather_evidence",
            latency_ms=(time.perf_counter() - start_t) * 1000,
            status="RUNNING",
            details={"lines_count": len(lines), "rules_count": len(rules), "events_count": len(events)},
        )
        return {
            "status": "RUNNING",
            "evidence_version": case.evidence_version,
            "case_data": {
                "id": case.id,
                "title": case.title,
                "customer_name": case.customer_name,
                "disputed_amount_cents": case.disputed_amount_cents,
                "dispute_description": case.dispute_description,
            },
            "dispute_text": case.dispute_description or f"{case.title}. Customer: {case.customer_name}.",
            "invoice_lines": [
                {"id": l.id, "description": l.description, "original_amount_cents": l.original_amount_cents}
                for l in lines
            ],
            "contract_rules": [
                {
                    "id": r.id,
                    "line_id": r.line_id,
                    "rule_type": r.rule_type.value,
                    "rate_cents": r.rate_cents,
                    "tiers": r.tiers,
                    "discount_pct": float(r.discount_pct) if r.discount_pct is not None else None,
                    "included_units": r.included_units,
                    "overage_rate_cents": r.overage_rate_cents,
                    "minimum_commit_cents": r.minimum_commit_cents,
                    "exempt_environments": r.exempt_environments,
                }
                for r in rules
            ],
            "usage_events": [
                {"id": e.id, "line_id": e.line_id, "quantity": float(e.quantity), "environment": e.environment}
                for e in events
            ],
            "adjustments": [
                {
                    "id": a.id,
                    "invoice_line_id": a.invoice_line_id,
                    "amount_cents": a.amount_cents,
                    "description": a.description,
                }
                for a in adjustments
            ],
        }

    def run_calculation_node(self, state: AgentState) -> dict[str, Any]:
        """Invokes the deterministic calculation engine."""
        start_t = time.perf_counter()
        calc = execute_case_calculation(
            db=self.db,
            case_id=state["case_id"],
            actor=state["actor"],
            correlation_id=state.get("correlation_id"),
        )

        line_results = []
        valid_result_ids = []
        for lr in calc.line_results:
            line_results.append({
                "id": lr.id,
                "line_id": lr.line_id,
                "result_id": lr.result_id,
                "original_amount_cents": lr.original_amount_cents,
                "recalculated_amount_cents": lr.recalculated_amount_cents,
                "difference_cents": lr.difference_cents,
                "finding_type": lr.finding_type.value,
                "explanation": lr.explanation,
                "quantity_used": float(lr.quantity_used) if lr.quantity_used is not None else 0.0,
                "exempt_quantity": float(lr.exempt_quantity) if lr.exempt_quantity is not None else 0.0,
                "interpretations": [
                    {
                        "interpretation_id": it.get("interpretation_id") if isinstance(it, dict) else getattr(it, "interpretation_id", ""),
                        "recalculated_amount_cents": it.get("recalculated_amount_cents", 0) if isinstance(it, dict) else getattr(it, "recalculated_amount_cents", 0),
                        "assumptions": it.get("assumptions", []) if isinstance(it, dict) else getattr(it, "assumptions", []),
                    }
                    for it in (lr.interpretations or [])
                ],
                "undisputed_overcharge_cents": lr.undisputed_overcharge_cents,
            })
            valid_result_ids.append(lr.result_id)

        log_agent_node_execution(
            run_id=state["run_id"],
            case_id=state["case_id"],
            node="run_calculation",
            latency_ms=(time.perf_counter() - start_t) * 1000,
            status=calc.engine_status.value,
            details={"diff_cents": calc.total_difference_cents, "lines_count": len(line_results)},
        )

        # Collect all quarantined events from calculation-level (unattached) and line results
        all_quarantined = []
        seen_q_ids = set()
        for q in (calc.quarantined_events or []):
            eid = q.get("event_id") if isinstance(q, dict) else getattr(q, "event_id", str(q))
            reason = q.get("reason") if isinstance(q, dict) else getattr(q, "reason", "Quarantined")
            if eid not in seen_q_ids:
                seen_q_ids.add(eid)
                all_quarantined.append({"event_id": eid, "reason": reason})

        for lr in calc.line_results:
            for q in (lr.quarantined_events or []):
                eid = q.get("event_id") if isinstance(q, dict) else getattr(q, "event_id", str(q))
                reason = q.get("reason") if isinstance(q, dict) else getattr(q, "reason", "Quarantined")
                if eid not in seen_q_ids:
                    seen_q_ids.add(eid)
                    all_quarantined.append({"event_id": eid, "reason": reason})

        return {
            "calculation_id": calc.id,
            "calculation_status": calc.engine_status.value,
            "calculation_status_reason": calc.engine_status_reason,
            "total_original_billed_cents": calc.total_original_billed_cents,
            "total_recalculated_cents": calc.total_recalculated_cents,
            "total_difference_cents": calc.total_difference_cents,
            "result_hash": calc.result_hash,
            "line_results": line_results,
            "valid_result_ids": valid_result_ids,
            "quarantined_events": all_quarantined,
        }

    def analyze_findings_node(self, state: AgentState) -> dict[str, Any]:
        """Calls LLM Call 1 to produce structured investigation findings per disputed line (or overall if clean)."""
        start_t = time.perf_counter()
        line_results = state.get("line_results", [])
        calc_status = state.get("calculation_status", "OK")

        # Determine target lines: lines that are not NO_DISCREPANCY, or overall if all clean
        discrepant_lrs = []
        for lr in line_results:
            lr_type = validator.derive_engine_finding_type([lr], lr.get("finding_type", calc_status))
            if lr_type != "NO_DISCREPANCY":
                discrepant_lrs.append(lr)

        target_lrs = discrepant_lrs if discrepant_lrs else ([line_results[0]] if line_results else [None])

        raw_findings = []
        token_usage = dict(state.get("token_usage") or {})
        any_llm_fallback = False

        for t_lr in target_lrs:
            f_dict, tokens = llm_client.generate_investigation_findings(state, target_lr=t_lr)
            if f_dict.get("generation_path") == "fallback_mock":
                any_llm_fallback = True
            for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
                if k in tokens and isinstance(tokens[k], (int, float)):
                    token_usage[k] = token_usage.get(k, 0) + tokens[k]
            if tokens.get("provider"):
                token_usage["provider"] = tokens["provider"]
            if tokens.get("model"):
                token_usage["model"] = tokens["model"]
            if "attempts" in tokens and isinstance(tokens["attempts"], list):
                existing_att = token_usage.get("attempts", [])
                for att in tokens["attempts"]:
                    if att not in existing_att:
                        existing_att.append(att)
                token_usage["attempts"] = existing_att
            raw_findings.append(f_dict)

        log_agent_node_execution(
            run_id=state["run_id"],
            case_id=state["case_id"],
            node="analyze_findings",
            latency_ms=(time.perf_counter() - start_t) * 1000,
            status=raw_findings[0].get("finding_type", "UNRESOLVED") if raw_findings else "OK",
            token_usage=token_usage,
            details={"findings_count": len(raw_findings)},
        )
        return {
            "raw_findings": raw_findings,
            "token_usage": token_usage,
            "llm_fallback": any_llm_fallback,
        }

    def formulate_options_node(self, state: AgentState) -> dict[str, Any]:
        """Calls LLM Call 2 to formulate resolution options per finding."""
        start_t = time.perf_counter()
        raw_findings = state.get("raw_findings", [])
        token_usage = dict(state.get("token_usage") or {})
        all_raw_options = []

        for f in raw_findings:
            options_list, tokens = llm_client.generate_resolution_options(state, f)
            for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
                if k in tokens and isinstance(tokens[k], (int, float)):
                    token_usage[k] = token_usage.get(k, 0) + tokens[k]
            if tokens.get("provider"):
                token_usage["provider"] = tokens["provider"]
            if tokens.get("model"):
                token_usage["model"] = tokens["model"]
            if "attempts" in tokens and isinstance(tokens["attempts"], list):
                existing_attempts = token_usage.get("attempts", [])
                for att in tokens["attempts"]:
                    if att not in existing_attempts:
                        existing_attempts.append(att)
                token_usage["attempts"] = existing_attempts

            # Anchor each option to this finding's calculation_line_result_id if not set
            for opt in options_list:
                if not opt.get("calculation_line_result_id"):
                    opt["calculation_line_result_id"] = f.get("calculation_line_result_id")
                all_raw_options.append(opt)

        log_agent_node_execution(
            run_id=state["run_id"],
            case_id=state["case_id"],
            node="formulate_options",
            latency_ms=(time.perf_counter() - start_t) * 1000,
            status="OK",
            token_usage=token_usage,
            details={"options_count": len(all_raw_options)},
        )

        return {
            "raw_options": all_raw_options,
            "token_usage": token_usage,
        }

    def validate_and_sanitize_node(self, state: AgentState) -> dict[str, Any]:
        """Applies schema validation, citation validation, consistency checks, and option sanitization per finding."""
        start_t = time.perf_counter()
        raw_findings = state.get("raw_findings", [])
        valid_result_ids = state.get("valid_result_ids", [])
        valid_line_ids = [l.get("id") for l in state.get("invoice_lines", []) if l.get("id")]
        valid_rule_ids = [r.get("id") for r in state.get("contract_rules", []) if r.get("id")]
        valid_usage_ids = [e.get("id") for e in state.get("usage_events", []) if e.get("id")]
        valid_adj_ids = [a.get("id") for a in state.get("adjustments", []) if a.get("id")]
        all_valid_citations = list(set(valid_result_ids + valid_line_ids + valid_rule_ids + valid_usage_ids + valid_adj_ids))

        calc_status = state.get("calculation_status", "OK")
        total_diff = state.get("total_difference_cents", 0)
        line_results = state.get("line_results", [])
        raw_options = state.get("raw_options", [])

        validated_findings = []
        validated_options = []

        for rf in raw_findings:
            # Find the line result this finding is for
            lr_id = rf.get("calculation_line_result_id")
            target_lr = next((lr for lr in line_results if lr.get("id") == lr_id), None)
            target_line_id = target_lr.get("line_id") if target_lr else (
                state.get("invoice_lines", [{}])[0].get("id") if len(state.get("invoice_lines", [])) == 1 else None
            )

            # Determine line-level engine status and line results for this finding
            finding_line_results = [target_lr] if target_lr else line_results
            finding_calc_status = target_lr.get("finding_type", calc_status) if target_lr else calc_status
            finding_diff = target_lr.get("difference_cents", total_diff) if target_lr else total_diff

            # 0. Validate raw LLM JSON schema & line result ID against this run
            payload_passed, sanitized_rf, p_errs = validator.validate_llm_payload(rf, line_results)

            raw_model_text = rf.get("summary_narrative") or sanitized_rf.get("summary_narrative") or ""

            # 1. Validate rich citations
            citation_passed, sanitized_citations, c_errs = validator.validate_citations(
                sanitized_rf, all_valid_citations
            )

            # 2. Consistency check per line
            consist_passed, final_finding_type, con_errs = validator.validate_consistency(
                sanitized_rf, finding_calc_status, finding_diff, finding_line_results
            )

            # 3. Narrative monetary check
            summary_calc = {
                "total_original_billed_cents": target_lr.get("original_amount_cents", state.get("total_original_billed_cents", 0)) if target_lr else state.get("total_original_billed_cents", 0),
                "total_recalculated_cents": target_lr.get("recalculated_amount_cents", state.get("total_recalculated_cents", 0)) if target_lr else state.get("total_recalculated_cents", 0),
                "total_difference_cents": finding_diff,
            }
            narrative_passed, nar_errs = validator.validate_narrative_amounts(
                sanitized_rf,
                finding_line_results,
                summary_calc,
                contract_rules=state.get("contract_rules", []),
                adjustments=state.get("adjustments", []),
                case_data=state.get("case_data", {}),
            )
            if not narrative_passed or not payload_passed:
                consist_passed = False
                logger.warning("Validation failed: narrative=%s, payload=%s", nar_errs, p_errs)

            f_copy = dict(sanitized_rf)
            f_copy["invoice_line_id"] = target_line_id
            f_copy["raw_ai_text"] = raw_model_text
            f_copy["citation_ids"] = sanitized_citations
            f_copy["citation_validation_passed"] = citation_passed
            f_copy["consistency_check_passed"] = consist_passed
            f_copy["finding_type"] = final_finding_type

            val_notes = list(con_errs) + list(nar_errs) + list(p_errs)

            # If model's finding_type differed from engine or narrative failed, replace narrative fields with deterministic engine narrative
            if not consist_passed:
                engine_narrative = validator.generate_engine_narrative(final_finding_type, finding_line_results, finding_calc_status)
                f_copy["summary_narrative"] = engine_narrative
                f_copy["narrative"] = engine_narrative
                f_copy["verified_facts"] = [
                    f"Deterministic engine calculated status: {finding_calc_status}",
                    f"Recalculation difference: {finding_diff}¢",
                ]
                f_copy["possible_explanations"] = [
                    f"AI finding narrative was replaced with deterministic engine evaluation due to contradiction with engine status ({final_finding_type})."
                ]
            else:
                f_copy["narrative"] = sanitized_rf.get("summary_narrative", "")

            # Require that when final type is CONFIRMED_CALCULATION_DISCREPANCY, calculation_line_result_id
            # is not null and points to an overcharged line; if null/invalid, set it to the target_lr or largest-overcharge line.
            if final_finding_type == "CONFIRMED_CALCULATION_DISCREPANCY":
                overcharged_lines = [lr for lr in line_results if lr.get("difference_cents") is not None and lr.get("difference_cents") < 0]
                overcharged_ids = {lr.get("id") for lr in overcharged_lines if lr.get("id") is not None}
                curr_line_id = f_copy.get("calculation_line_result_id")
                if curr_line_id is None or curr_line_id not in overcharged_ids:
                    if target_lr and target_lr.get("difference_cents") is not None and target_lr.get("difference_cents") < 0:
                        f_copy["calculation_line_result_id"] = target_lr.get("id")
                    elif overcharged_lines:
                        largest = min(overcharged_lines, key=lambda lr: lr.get("difference_cents") if lr.get("difference_cents") is not None else 0)
                        f_copy["calculation_line_result_id"] = largest.get("id")
                        val_notes.append(
                            f"Calculation line result ID was unset or not overcharged; defaulted to line result {largest.get('id')} ({largest.get('line_id')}) with largest overcharge ({largest.get('difference_cents')}¢)"
                        )

            f_copy["validation_notes"] = val_notes

            if val_notes:
                current_assumptions = list(f_copy.get("assumptions") or [])
                for vn in val_notes:
                    if vn not in current_assumptions:
                        current_assumptions.append(f"Validation Note: {vn}")
                f_copy["assumptions"] = current_assumptions

            validated_findings.append(f_copy)

            # Sanitize resolution options for THIS finding
            finding_target_id = f_copy.get("calculation_line_result_id")
            matching_raw_opts = [
                opt for opt in raw_options
                if opt.get("calculation_line_result_id") == finding_target_id or opt.get("calculation_line_result_id") is None
            ]
            opts_for_this_finding = validator.sanitize_resolution_options(
                matching_raw_opts, finding_line_results, finding_type=final_finding_type
            )
            for so in opts_for_this_finding:
                if finding_target_id and not so.get("calculation_line_result_id") and so.get("option_type") == "RECOMMEND_CREDIT":
                    so["calculation_line_result_id"] = finding_target_id
                so["invoice_line_id"] = target_line_id
                if so not in validated_options:
                    validated_options.append(so)

        # 5. Status: if LLM fallback occurred, mark as PARTIAL
        status_val = "COMPLETED"
        status_reason = None
        if state.get("llm_fallback"):
            status_val = "PARTIAL"
            status_reason = "LLM analysis failed or unconfigured; deterministic fallback applied"

        log_agent_node_execution(
            run_id=state["run_id"],
            case_id=state["case_id"],
            node="validate_and_sanitize",
            latency_ms=(time.perf_counter() - start_t) * 1000,
            status=status_val,
        )

        return {
            "validated_findings": validated_findings,
            "validated_options": validated_options,
            "status": status_val,
            "status_reason": status_reason,
        }

    def persist_results_node(self, state: AgentState) -> dict[str, Any]:
        """Persists the InvestigationRun, Findings, and ResolutionOptions to DB."""
        start_t = time.perf_counter()
        run_id = state["run_id"]
        status_val = state.get("status", "COMPLETED")

        # Check if newer evidence arrived while this investigation was in flight
        current_case = self.db.query(Case).filter(Case.id == state["case_id"]).first()
        is_stale_run = bool(
            current_case is not None and current_case.evidence_version > state.get("evidence_version", 1)
        )
        if is_stale_run:
            status_val = "DISCARDED"
            state["status_reason"] = "Investigation superseded by newer evidence uploaded concurrently"

        # 1. Update existing InvestigationRun record (created at start of run_investigation)
        db_run = self.db.query(InvestigationRun).filter(InvestigationRun.id == run_id).one_or_none()
        if db_run:
            db_run.status = RunStatus(status_val)
            db_run.status_reason = state.get("status_reason")
            db_run.calculation_id = state.get("calculation_id")
            db_run.token_usage = state.get("token_usage")
            db_run.completed_at = datetime.now(timezone.utc)
        else:
            db_run = InvestigationRun(
                id=run_id,
                case_id=state["case_id"],
                calculation_id=state.get("calculation_id"),
                evidence_version=state.get("evidence_version", 1),
                status=RunStatus(status_val),
                status_reason=state.get("status_reason"),
                token_usage=state.get("token_usage"),
                completed_at=datetime.now(timezone.utc),
            )
            self.db.add(db_run)

        # If BLOCKED, DISCARDED, or FAILED, do NOT create active findings
        if status_val in ("BLOCKED", "DISCARDED", "FAILED"):
            audit_event = CaseEvent(
                case_id=state["case_id"],
                event_type=f"INVESTIGATION_RUN_{status_val}",
                actor=state["actor"],
                details={
                    "run_id": run_id,
                    "reason": state.get("status_reason"),
                    "evidence_version": state.get("evidence_version"),
                },
                correlation_id=state.get("correlation_id"),
            )
            self.db.add(audit_event)
            self.db.commit()
            return {"status": status_val}

        # 2. Mark prior findings and options for this case as superseded / stale
        self.db.query(Finding).filter(
            Finding.case_id == state["case_id"],
            Finding.is_stale == False,  # noqa: E712
        ).update({"is_stale": True, "stale_reason": f"Superseded by investigation run {run_id}"})

        self.db.query(ResolutionOption).filter(
            ResolutionOption.case_id == state["case_id"],
            ResolutionOption.is_stale == False,  # noqa: E712
        ).update({"is_stale": True, "stale_reason": f"Superseded by investigation run {run_id}"})
        self.db.flush()

        # 3. Persist Findings
        db_findings = []
        for vf in state.get("validated_findings", []):
            f_id = f"fnd_{uuid.uuid4().hex[:12]}"
            db_finding = Finding(
                id=f_id,
                run_id=run_id,
                case_id=state["case_id"],
                invoice_line_id=vf.get("invoice_line_id"),
                finding_type=AgentFindingType(vf.get("finding_type", "UNRESOLVED")),
                narrative=vf.get("narrative") or vf.get("summary_narrative"),
                raw_ai_text=vf.get("raw_ai_text") or vf.get("summary_narrative"),
                calculation_line_result_id=vf.get("calculation_line_result_id"),
                verified_facts=vf.get("verified_facts"),
                possible_explanations=vf.get("possible_explanations"),
                assumptions=vf.get("assumptions"),
                open_questions=vf.get("open_questions"),
                missing_evidence_questions=vf.get("missing_evidence_questions"),
                citation_ids=vf.get("citation_ids"),
                citation_validation_passed=vf.get("citation_validation_passed", False),
                consistency_check_passed=vf.get("consistency_check_passed", False),
                validation_notes=vf.get("validation_notes"),
                is_stale=False,
            )
            self.db.add(db_finding)
            db_findings.append(db_finding)

        # 3. Persist ResolutionOptions
        db_options = []
        for vo in state.get("validated_options", []):
            o_id = f"opt_{uuid.uuid4().hex[:12]}"
            db_opt = ResolutionOption(
                id=o_id,
                run_id=run_id,
                case_id=state["case_id"],
                invoice_line_id=vo.get("invoice_line_id"),
                option_type=OptionType(vo["option_type"]),
                description=vo.get("description", ""),
                calculation_line_result_id=vo.get("calculation_line_result_id"),
                is_stale=False,
            )
            self.db.add(db_opt)
            db_options.append(db_opt)

        # 4. Append-only audit log
        audit_event = CaseEvent(
            case_id=state["case_id"],
            event_type="INVESTIGATION_RUN_COMPLETED",
            actor=state["actor"],
            details={
                "run_id": run_id,
                "calculation_id": state.get("calculation_id"),
                "status": status_val,
                "findings_count": len(db_findings),
                "options_count": len(db_options),
                "evidence_version": state.get("evidence_version"),
            },
            correlation_id=state.get("correlation_id"),
        )
        self.db.add(audit_event)
        self.db.commit()

        log_agent_node_execution(
            run_id=run_id,
            case_id=state["case_id"],
            node="persist_results",
            latency_ms=(time.perf_counter() - start_t) * 1000,
            status=status_val,
            token_usage=state.get("token_usage"),
            details={"findings_count": len(db_findings), "options_count": len(db_options)},
        )
        return {"status": "COMPLETED"}


def run_investigation(
    db: Session,
    case_id: str,
    actor: str,
    correlation_id: Optional[str] = None,
) -> InvestigationRun:
    """Entrypoint function to instantiate the workflow and execute the LangGraph StateGraph."""
    run_id = f"run_{uuid.uuid4().hex[:12]}"

    case = db.query(Case).filter(Case.id == case_id).one_or_none()
    evidence_version = case.evidence_version if case else 1

    # Insert InvestigationRun as RUNNING immediately to activate concurrent repeat-run guard
    running_run = InvestigationRun(
        id=run_id,
        case_id=case_id,
        status=RunStatus.RUNNING,
        evidence_version=evidence_version,
        token_usage={
            "provider": None,
            "model": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "attempts": [],
        },
        started_at=datetime.now(timezone.utc),
    )
    db.add(running_run)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    initial_state: AgentState = {
        "case_id": case_id,
        "run_id": run_id,
        "actor": actor,
        "correlation_id": correlation_id,
        "evidence_version": evidence_version,
        "status": "RUNNING",
        "token_usage": {},
        "errors": [],
        "warnings": [],
    }

    workflow = InvestigationWorkflow(db)
    try:
        workflow.graph.invoke(initial_state)
    except Exception as e:
        logger.error("Investigation workflow failed: %s", e)
        db.rollback()

        # Find existing calculation if one exists for this case
        calc = (
            db.query(Calculation)
            .filter(Calculation.case_id == case_id)
            .order_by(Calculation.created_at.desc())
            .first()
        )
        calc_id = calc.id if calc else None

        # Update existing InvestigationRun to FAILED
        failed_run = db.query(InvestigationRun).filter(InvestigationRun.id == run_id).one_or_none()
        attempts = getattr(e, "attempts", [])
        clean_reason = llm_client.sanitize_error_message(str(e))
        if failed_run:
            failed_run.status = RunStatus.FAILED
            failed_run.status_reason = clean_reason
            if calc_id and not failed_run.calculation_id:
                failed_run.calculation_id = calc_id
            failed_run.token_usage = {
                "provider": None,
                "model": None,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "attempts": attempts,
            }
            failed_run.completed_at = datetime.now(timezone.utc)
        else:
            failed_run = InvestigationRun(
                id=run_id,
                case_id=case_id,
                calculation_id=calc_id,
                status=RunStatus.FAILED,
                status_reason=clean_reason,
                evidence_version=evidence_version,
                token_usage={
                    "provider": None,
                    "model": None,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "attempts": attempts,
                },
                completed_at=datetime.now(timezone.utc),
            )
            db.add(failed_run)

        failed_event = CaseEvent(
            case_id=case_id,
            event_type="INVESTIGATION_RUN_FAILED",
            actor=actor,
            details={
                "run_id": run_id,
                "actor": actor,
                "reason": clean_reason,
                "attempts": attempts,
                "evidence_version": evidence_version,
            },
            correlation_id=correlation_id,
        )
        db.add(failed_event)
        db.commit()
        return failed_run
    finally:
        # Guarantee run never remains in RUNNING under any circumstance
        try:
            check_run = db.query(InvestigationRun).filter(InvestigationRun.id == run_id).one_or_none()
            if check_run and check_run.status == RunStatus.RUNNING:
                check_run.status = RunStatus.FAILED
                check_run.status_reason = check_run.status_reason or "Investigation execution exited without completing"
                check_run.completed_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            logger.exception("Error verifying run completion status in finally block")

    # Return refreshed InvestigationRun
    db_run = db.query(InvestigationRun).filter(InvestigationRun.id == run_id).one()
    return db_run

