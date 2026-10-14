"""
main.py
=======
FastAPI application entrypoint for Billing Dispute Investigation and Resolution Agent.
Serves both REST API endpoints and built React frontend assets.
"""

import math
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import create_all_tables
from app.logging import StructuredLoggingMiddleware, setup_structured_logging
from app.routers import (
    cases_router,
    evidence_router,
    calculations_router,
    findings_router,
    credits_router,
    investigations_router,
    llm_router,
)

# Initialize structured JSON logging
setup_structured_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup tables and append-only triggers on startup for dev/test
    create_all_tables()
    # Auto-seed initial demo dispute cases if database is brand new / empty
    try:
        from app.database import SessionLocal
        from app.models.case import Case, CaseStatus
        from app.models.invoice import InvoiceLine, ContractRule
        from app.models.evidence import EvidenceEvent
        from datetime import datetime, timezone
        
        db = SessionLocal()
        try:
            if db.query(Case).count() == 0:
                # 1. Acme Corp (Metered Tier Overcharge)
                c1 = Case(
                    id="case-acme-101",
                    title="Metered API Tier Overcharge",
                    customer_name="Acme Corp",
                    disputed_amount_cents=2500,
                    dispute_description="Customer reports overcharge of $25.00 on production API calls. Telemetry logs show 250 production calls and 150 staging calls; staging calls were improperly counted towards billable tier.",
                    status=CaseStatus.OPEN.value,
                    evidence_version=1,
                )
                db.add(c1)
                db.flush()
                db.add(InvoiceLine(id="line-api-calls", case_id=c1.id, description="Production API Metered Requests", original_amount_cents=5000))
                db.add(ContractRule(id="rule-api-rate", line_id="line-api-calls", rule_type="PER_UNIT", rate_cents=10, exempt_environments=["staging", "test"]))
                db.add(EvidenceEvent(case_id=c1.id, event_id="ev-acme-prod-1", line_id="line-api-calls", timestamp=datetime.now(timezone.utc), quantity=250.0, environment="production"))
                db.add(EvidenceEvent(case_id=c1.id, event_id="ev-acme-stg-1", line_id="line-api-calls", timestamp=datetime.now(timezone.utc), quantity=150.0, environment="staging"))

                # 2. Bravo Ltd (Contract Ambiguity)
                c2 = Case(
                    id="case-bravo-102",
                    title="Underspecified Tiered Pricing Clause",
                    customer_name="Bravo Ltd",
                    disputed_amount_cents=1500,
                    dispute_description="Dispute regarding tier calculation method on 200 compute units. Contract rule card contains competing graduated and volume interpretations.",
                    status=CaseStatus.OPEN.value,
                    evidence_version=1,
                )
                db.add(c2)
                db.flush()
                db.add(InvoiceLine(id="line-compute-units", case_id=c2.id, description="Compute Units Band A", original_amount_cents=4000))
                db.add(ContractRule(id="rule-tiered-grad", line_id="line-compute-units", rule_type="TIERED_GRADUATED", rate_cents=0, tiers=[{"up_to": 100, "price_per_unit_cents": 15}, {"up_to": None, "price_per_unit_cents": 10}]))
                db.add(ContractRule(id="rule-tiered-vol", line_id="line-compute-units", rule_type="TIERED_VOLUME", rate_cents=0, tiers=[{"up_to": 100, "price_per_unit_cents": 15}, {"up_to": None, "price_per_unit_cents": 10}]))
                db.add(EvidenceEvent(case_id=c2.id, event_id="ev-bravo-1", line_id="line-compute-units", timestamp=datetime.now(timezone.utc), quantity=200.0, environment="production"))

                # 3. Delta Cloud (Clean Invoice)
                c3 = Case(
                    id="case-delta-103",
                    title="Clean Fixed Platform Subscription",
                    customer_name="Delta Cloud",
                    disputed_amount_cents=0,
                    dispute_description="Customer inquiry regarding $100.00 base platform subscription fee. Recalculation confirms billed amount is exact per flat contract rule.",
                    status=CaseStatus.OPEN.value,
                    evidence_version=1,
                )
                db.add(c3)
                db.flush()
                db.add(InvoiceLine(id="line-platform-sub", case_id=c3.id, description="Monthly Platform Fee", original_amount_cents=10000))
                db.add(ContractRule(id="rule-sub-flat", line_id="line-platform-sub", rule_type="FLAT", rate_cents=10000))

                db.commit()
        finally:
            db.close()
    except Exception:
        pass
    yield


app = FastAPI(
    title="FairBill: Billing Dispute Investigation & Resolution Platform",
    description="Deterministic billing calculation and AI-assisted dispute resolution platform",
    version=settings.app_version,
    lifespan=lifespan,
)


def _sanitize_validation_errors(obj):
    """Recursively replaces non-finite float values and exception objects so json.dumps doesn't crash."""
    if isinstance(obj, float):
        if math.isnan(obj):
            return "NaN"
        if math.isinf(obj):
            return "Infinity" if obj > 0 else "-Infinity"
        return obj
    if isinstance(obj, (int, str, bool)) or obj is None:
        return obj
    if isinstance(obj, dict):
        return {str(k): _sanitize_validation_errors(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_sanitize_validation_errors(item) for item in obj]
    return str(obj)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    sanitized_errors = _sanitize_validation_errors(exc.errors())
    return JSONResponse(
        status_code=422,
        content={"detail": sanitized_errors},
    )


app.add_middleware(StructuredLoggingMiddleware)

# CORS configuration
configured_origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
if not configured_origins or configured_origins == ["*"]:
    # Fallback to local Vite dev/preview origins when unspecified, avoiding illegal wildcard + credentials combo
    origins = ["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"]
    allow_credentials = True
else:
    origins = configured_origins
    allow_credentials = True

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API Routers
app.include_router(cases_router)
app.include_router(evidence_router)
app.include_router(calculations_router)
app.include_router(findings_router)
app.include_router(credits_router)
app.include_router(investigations_router)
app.include_router(llm_router)


@app.get("/healthz", tags=["health"])
def health_check():
    """Liveness probe for Render and orchestrators."""
    return {"status": "ok", "version": settings.app_version}


# ── Frontend SPA Mounting ─────────────────────────────────────────────────────
# If the React frontend has been built into frontend/dist, serve it directly
# so that the service runs as a unified full-stack application.
FRONTEND_DIST = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
)

if os.path.isdir(FRONTEND_DIST):
    assets_dir = os.path.join(FRONTEND_DIST, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_frontend_spa(full_path: str):
        # Do not intercept API, health probe, or docs paths
        if (
            full_path.startswith("api/")
            or full_path.startswith("healthz")
            or full_path in ("docs", "redoc", "openapi.json")
        ):
            raise HTTPException(status_code=404, detail="Not Found")

        root = os.path.realpath(FRONTEND_DIST)
        file_path = os.path.realpath(os.path.join(root, full_path))

        # Containment check: prevent path traversal attacks (e.g. /../../backend/requirements.txt)
        if file_path.startswith(root + os.sep) and os.path.isfile(file_path):
            return FileResponse(file_path)

        index_file = os.path.join(root, "index.html")
        if os.path.isfile(index_file):
            return FileResponse(index_file)
        raise HTTPException(status_code=404, detail="Frontend index.html not found")
else:
    @app.get("/", tags=["health"])
    def root():
        return {
            "name": "FairBill API",
            "version": settings.app_version,
            "status": "online",
            "docs": "/docs",
            "frontend": "Not built; run 'npm run build' in /frontend to bundle UI.",
        }
