"""
test_ai_quality_gates.py
========================
Tests for Task 5: AI Output Quality Gates
a) missing_evidence_questions validation:
   - Drop empty or duplicate questions
   - Drop all when finding is CONFIRMED_CALCULATION_DISCREPANCY and telemetry is complete
b) Grounded root-cause hypotheses:
   - May only state a cause derivable from evidence; otherwise "Cause cannot be determined from the provided evidence"
   - Rejects hypotheses asserting specific rates/mechanisms (e.g. "flat rate") not present in contract rules
   - Test with fake provider returning ungrounded hypothesis
c) Monetary amount scan:
   - Catches "5,000 USD", "EUR 5000", "5000 dollars", "five thousand dollars", etc.
"""

import pytest
from app.agent.validator import (
    extract_monetary_amounts_cents,
    parse_words_to_number,
    validate_hypotheses_grounding,
    validate_llm_payload,
    validate_narrative_amounts,
)


class TestMissingEvidenceQuestions:
    def test_drops_empty_and_duplicate_questions(self):
        raw = {
            "finding_type": "INSUFFICIENT_EVIDENCE",
            "summary_narrative": "Missing telemetry for staging",
            "missing_evidence_questions": [
                "  ",
                "Where are the production logs?",
                "Where are the production logs?",
                "",
                "What is the contract addendum date?",
            ],
            "open_questions": [
                "Who signed the contract?",
                "Who signed the contract?",
                "   ",
            ],
        }
        passed, sanitized, errs = validate_llm_payload(raw, line_results=[])
        assert passed
        assert sanitized["missing_evidence_questions"] == [
            "Where are the production logs?",
            "What is the contract addendum date?",
        ]
        assert sanitized["open_questions"] == [
            "Who signed the contract?",
        ]

    def test_drops_all_questions_on_confirmed_discrepancy_with_complete_telemetry(self):
        raw = {
            "finding_type": "CONFIRMED_CALCULATION_DISCREPANCY",
            "summary_narrative": "Confirmed rate calculation discrepancy on compute line",
            "missing_evidence_questions": [
                "Can you provide more telemetry for October?",
            ],
        }
        # When quarantined_events is empty, telemetry is complete
        passed, sanitized, errs = validate_llm_payload(raw, line_results=[], quarantined_events=[])
        assert passed
        assert sanitized["missing_evidence_questions"] == []


class TestRootCauseHypothesesGrounding:
    def test_rejects_ungrounded_mechanism(self):
        contract_rules = [{"rule_type": "TIERED_GRADUATED", "rate_cents": 80}]
        hypotheses = [
            "The discrepancy was caused by an inadvertent flat rate being billed instead of tiered pricing.",
            "Usage crossed into the higher graduated tier.",
        ]
        grounded = validate_hypotheses_grounding(hypotheses, contract_rules=contract_rules)
        assert len(grounded) == 2
        assert grounded[0] == "Cause cannot be determined from the provided evidence"
        assert grounded[1] == "Usage crossed into the higher graduated tier."

    def test_fallback_when_all_ungrounded(self):
        contract_rules = [{"rule_type": "TIERED_GRADUATED"}]
        hypotheses = [
            "A flat fee was incorrectly applied.",
            "Minimum commit floor commitment was violated.",
        ]
        grounded = validate_hypotheses_grounding(hypotheses, contract_rules=contract_rules)
        assert grounded == ["Cause cannot be determined from the provided evidence"]

    def test_fake_provider_returning_ungrounded_hypothesis_is_sanitized_in_graph(self):
        from unittest.mock import MagicMock
        from app.agent.graph import InvestigationWorkflow

        fake_finding = {
            "finding_type": "CONFIRMED_CALCULATION_DISCREPANCY",
            "summary_narrative": "Deterministic billing engine confirmed an overcharge totaling €490.00 across line item(s): line-1 (billed €1,250.00, recalculated €760.00). Discrepancy is eligible for credit approval.",
            "verified_facts": ["1800 units used."],
            "possible_explanations": ["Discrepancy caused by flat rate pricing mismatch."],
            "assumptions": [],
            "open_questions": [],
            "missing_evidence_questions": [],
            "citation_ids": ["res_mock_1234"],
            "calculation_line_result_id": 1,
        }

        mock_db = MagicMock()
        workflow = InvestigationWorkflow(mock_db)

        state = {
            "run_id": "test-run-1",
            "case_id": "test-fake-prov",
            "contract_rules": [{"id": "r1", "rule_type": "TIERED_GRADUATED", "line_id": "line-1"}],
            "invoice_lines": [{"id": "line-1", "original_amount_cents": 125000}],
            "line_results": [{
                "id": 1,
                "line_id": "line-1",
                "result_id": "res_mock_1234",
                "original_amount_cents": 125000,
                "recalculated_amount_cents": 76000,
                "difference_cents": -49000,
                "finding_type": "CONFIRMED_CALCULATION_DISCREPANCY",
            }],
            "raw_findings": [fake_finding],
            "raw_resolution_options": [],
            "total_difference_cents": -49000,
            "calculation_status": "OK",
            "quarantined_events": [],
            "case_data": {"currency": "EUR"},
        }

        result = workflow.validate_and_sanitize_node(state)
        findings = result.get("validated_findings", [])
        assert len(findings) == 1
        assert "Cause cannot be determined from the provided evidence" in findings[0]["possible_explanations"]
        assert not any("flat rate" in exp.lower() for exp in findings[0]["possible_explanations"])


class TestMonetaryAmountExtraction:
    @pytest.mark.parametrize(
        "text,expected_cents",
        [
            ("The customer claims 5,000 USD was overbilled.", 500000),
            ("Discrepancy of EUR 5000 identified on invoice.", 500000),
            ("Billed 5000 dollars instead of contract rate.", 500000),
            ("The total overcharge equals five thousand dollars exactly.", 500000),
            ("We observed an unexpected fifty dollars fee.", 5000),
            ("Recalculated line gives one hundred euros.", 10000),
            ("Discrepancy is €760.00.", 76000),
            ("Billed £45.00.", 4500),
        ],
    )
    def test_extracts_monetary_amounts(self, text, expected_cents):
        extracted = extract_monetary_amounts_cents(text)
        cents_found = [c for _, c, _ in extracted]
        assert expected_cents in cents_found, f"Failed to extract {expected_cents} cents from {text!r}: got {cents_found}"

    def test_fabricated_written_amount_triggers_validator(self):
        finding = {
            "summary_narrative": "Customer was overcharged five thousand dollars on compute.",
            "verified_facts": [],
            "possible_explanations": [],
        }
        # Allowed cents only includes 76000 and 125000
        line_results = [
            {"original_amount_cents": 125000, "recalculated_amount_cents": 76000, "difference_cents": -49000}
        ]
        summary = {"total_original_billed_cents": 125000, "total_recalculated_cents": 76000, "total_difference_cents": -49000}
        passed, errors = validate_narrative_amounts(finding, line_results, summary)
        assert not passed
        assert any("Fabricated monetary amount" in e and "500000¢" in e for e in errors)
