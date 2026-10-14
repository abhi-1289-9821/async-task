#!/usr/bin/env python3
"""
scripts/record_sample_run.py
============================
Executes a single real LLM investigation on case-acme-101 and records
the live provider, model, token usage, findings with citations, and
latency to docs/sample_run.json.

DO NOT FABRICATE DATA:
If real API keys are missing or all providers fail, the script fails loud
and exits without writing synthetic results.

Usage:
    cd backend
    python scripts/record_sample_run.py
"""

import json
import os
import sys
import time
from datetime import datetime, timezone

# Ensure backend root is on sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_root = os.path.abspath(os.path.join(current_dir, ".."))
project_root = os.path.abspath(os.path.join(backend_root, ".."))
if backend_root not in sys.path:
    sys.path.insert(0, backend_root)

from app.agent.graph import run_investigation
from app.agent.providers import get_provider
from app.config import settings
from app.database import SessionLocal, init_db
from app.models.case import Case
from app.models.investigation import Finding, InvestigationResolutionOption, InvestigationRun, RunStatus
from app.seed import seed_demo_cases_if_empty


def record_sample_run():
    print("=" * 60)
    print("FairBill — Real LLM Investigation Sample Run Recorder")
    print("=" * 60)

    # 1. Verify that real LLM mode is active and at least one provider is configured
    provider_names = [p.strip().lower() for p in settings.llm_providers.split(",") if p.strip()]
    configured_providers = []
    for name in provider_names:
        try:
            prov = get_provider(name)
            if prov.is_configured:
                configured_providers.append((name, prov.model))
        except Exception as e:
            print(f"Provider {name} error: {e}")

    if not configured_providers:
        print("\n[ERROR] No real LLM providers are configured in your local environment.")
        print("Please configure GEMINI_API_KEY, GROQ_API_KEY, or OPENROUTER_API_KEY in your .env file.")
        print("Real LLM output will NOT be fabricated.")
        sys.exit(1)

    print(f"Configured Providers: {', '.join(f'{n} ({m})' for n, m in configured_providers)}")
    settings.llm_mode = "real"

    # 2. Database preparation
    init_db()
    db = SessionLocal()
    try:
        seed_demo_cases_if_empty(db)
        case = db.query(Case).filter(Case.id == "case-acme-101").one_or_none()
        if not case:
            print("[ERROR] Demo case 'case-acme-101' not found in database.")
            sys.exit(1)

        print("\nTriggering live investigation for case-acme-101...")
        t_start = time.perf_counter()

        run: InvestigationRun = run_investigation(
            db=db,
            case_id="case-acme-101",
            actor="record_sample_run_script",
        )
        latency_ms = round((time.perf_counter() - t_start) * 1000, 2)

        if run.status != RunStatus.COMPLETED:
            print(f"\n[ERROR] Investigation run did not complete (status: {run.status}).")
            print(f"Reason: {run.status_reason}")
            sys.exit(1)

        # 3. Retrieve findings and resolution options
        findings = db.query(Finding).filter(Finding.run_id == run.id).all()
        options = (
            db.query(InvestigationResolutionOption)
            .filter(InvestigationResolutionOption.investigation_run_id == run.id)
            .all()
        )

        sample_record = {
            "case_id": "case-acme-101",
            "run_id": run.id,
            "status": run.status.value if hasattr(run.status, "value") else str(run.status),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "latency_ms": latency_ms,
            "latency_seconds": round(latency_ms / 1000, 3),
            "token_usage": run.token_usage or {},
            "findings": [
                {
                    "id": f.id,
                    "calculation_line_result_id": f.calculation_line_result_id,
                    "finding_type": f.finding_type.value if hasattr(f.finding_type, "value") else str(f.finding_type),
                    "narrative": f.narrative,
                    "raw_ai_text": f.raw_ai_text,
                    "citation_ids": f.citation_ids,
                    "citation_validation_passed": f.citation_validation_passed,
                    "consistency_check_passed": f.consistency_check_passed,
                    "verified_facts": f.verified_facts,
                    "possible_explanations": f.possible_explanations,
                    "missing_evidence_questions": f.missing_evidence_questions,
                    "open_questions": f.open_questions,
                    "validation_notes": f.validation_notes,
                }
                for f in findings
            ],
            "resolution_options": [
                {
                    "id": opt.id,
                    "option_type": opt.option_type.value if hasattr(opt.option_type, "value") else str(opt.option_type),
                    "description": opt.description,
                    "calculation_line_result_id": opt.calculation_line_result_id,
                }
                for opt in options
            ],
        }

        # 4. Write to docs/sample_run.json
        docs_dir = os.path.join(project_root, "docs")
        os.makedirs(docs_dir, exist_ok=True)
        sample_path = os.path.join(docs_dir, "sample_run.json")

        with open(sample_path, "w", encoding="utf-8") as f:
            json.dump(sample_record, f, indent=2)

        print("\n" + "=" * 60)
        print("Real LLM Investigation Successfully Recorded!")
        print("=" * 60)
        print(f"Output File: {sample_path}")
        print(f"Provider:    {run.token_usage.get('provider')}")
        print(f"Model:       {run.token_usage.get('model')}")
        print(f"Tokens:      {run.token_usage.get('total_tokens')}")
        print(f"Latency:     {latency_ms} ms ({round(latency_ms / 1000, 2)}s)")
        print(f"Findings:    {len(findings)}")
        print(f"Options:     {len(options)}")
        print("=" * 60)

    finally:
        db.close()


if __name__ == "__main__":
    record_sample_run()
