"""
schemas/evidence.py
===================
Pydantic v2 schemas for usage event upload and evidence versioning.
"""

from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


class UsageEventIn(BaseModel):
    event_id: str = Field(..., min_length=1, max_length=64)
    line_id: str = Field(..., min_length=1, max_length=36)
    timestamp: datetime
    quantity: float = Field(..., ge=0, allow_inf_nan=False)
    environment: str = Field(default="production", max_length=50)
    raw: Optional[dict[str, Any]] = None


class EvidenceUploadRequest(BaseModel):
    events: list[UsageEventIn] = Field(..., min_length=1)
    source_note: Optional[str] = Field(None, max_length=255)


class EvidenceUploadResponse(BaseModel):
    case_id: str
    new_evidence_version: int
    events_uploaded: int
    stale_findings_count: int
    case_status: str
    content_hash: str
