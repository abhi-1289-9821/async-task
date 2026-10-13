"""
main.py
=======
FastAPI application entrypoint for Billing Dispute Investigation and Resolution Agent.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import create_all_tables
from app.routers import (
    cases_router,
    evidence_router,
    calculations_router,
    findings_router,
    credits_router,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup tables and append-only triggers on startup for dev/test
    create_all_tables()
    yield


app = FastAPI(
    title="Billing Dispute Investigation & Resolution Agent",
    description="Deterministic billing calculation and AI-assisted dispute resolution platform",
    version=settings.app_version,
    lifespan=lifespan,
)

# CORS configuration
origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API Routers
app.include_router(cases_router)
app.include_router(evidence_router)
app.include_router(calculations_router)
app.include_router(findings_router)
app.include_router(credits_router)


@app.get("/healthz", tags=["health"])
def health_check():
    """Liveness probe for Render and orchestrators."""
    return {"status": "ok", "version": settings.app_version}


@app.get("/", tags=["health"])
def root():
    return {
        "name": "Billing Dispute Resolution API",
        "version": settings.app_version,
        "status": "online",
        "docs": "/docs",
    }
