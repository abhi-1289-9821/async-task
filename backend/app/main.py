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
