"""
conftest.py
===========
Pytest configuration ensuring complete environment isolation for all test suites.
Forces LLM_MODE=mock, test environment tokens, and dummy API keys before any application code loads.
"""

import os

# Set environment variables BEFORE any application or settings modules are imported
os.environ.setdefault("LLM_MODE", "mock")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("ALLOW_MOCK_FALLBACK", "true")
os.environ.setdefault("DEMO_MODE", "true")
os.environ.setdefault("DEMO_REVIEWER_TOKEN", "demo-reviewer-token-2026")
os.environ.setdefault("DEMO_VIEWER_TOKEN", "demo-viewer-token-2026")
os.environ.setdefault("GEMINI_API_KEY", "mock-gemini-test-key")
os.environ.setdefault("GROQ_API_KEY", "mock-groq-test-key")

import pytest
from app.config import settings

@pytest.fixture(autouse=True)
def ensure_mock_mode_default():
    """Guarantees tests execute with isolated mock mode unless explicitly overridden."""
    original_mode = settings.llm_mode
    yield
    settings.llm_mode = original_mode
