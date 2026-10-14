"""
tests/test_llm_resilience.py
=============================
Tests verifying multi-provider resilience and fallback:
1. Gemini 429 -> Groq success, provider recorded "groq".
2. Gemini and Groq fail -> OpenRouter success.
3. All fail -> FAILED run, audit event written, no findings created, HTTP 502.
4. Invalid JSON from first provider -> falls through to next provider.
5. 404 on a model -> skipped with no retry.
6. Provider without key or model is skipped.
7. response_format rejected (HTTP 400) -> retry without it succeeds.
8. Keys never appear in logs, errors, /api/llm/status or token_usage.
9. GET /api/llm/status returns configured status and model without keys.
"""

import json
import logging
import pytest
import httpx
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.agent import llm_client
from app.agent.providers import GeminiProvider, OpenAICompatProvider, get_provider
from app.config import Settings, settings
from app.database import Base, get_db, install_append_only_triggers, set_sqlite_pragmas
from app.main import app
from app.models.case import Case, CaseEvent
from app.models.calculation import Calculation
from app.models.investigation import Finding, InvestigationRun, RunStatus

REVIEWER_HEADERS = {"Authorization": f"Bearer {settings.demo_reviewer_token}"}
VIEWER_HEADERS = {"Authorization": f"Bearer {settings.demo_viewer_token}"}


@pytest.fixture
def test_db_client(tmp_path):
    db_file = tmp_path / "test_llm_resilience.sqlite"
    test_engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )
    event.listen(test_engine, "connect", set_sqlite_pragmas)
    Base.metadata.create_all(bind=test_engine)
    install_append_only_triggers(test_engine)

    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client, TestSession
    app.dependency_overrides.clear()


def make_test_case(client):
    client.post(
        "/api/cases",
        headers=REVIEWER_HEADERS,
        json={
            "id": "case-resilience-1",
            "title": "LLM Resilience Dispute",
            "customer_name": "Acme Corp",
            "disputed_amount_cents": 5000,
            "invoice_lines": [
                {"id": "line-res-1", "description": "Cloud Compute", "original_amount_cents": 5000}
            ],
            "contract_rules": [
                {"id": "rule-res-1", "line_id": "line-res-1", "rule_type": "PER_UNIT", "rate_cents": 10}
            ],
        },
    )


class TestLLMProviderFallback:
    def test_gemini_429_falls_back_to_groq_success(self, monkeypatch):
        """Gemini raises 429 quota exhaustion; retries once, then Groq succeeds."""
        monkeypatch.setattr(settings, "llm_mode", "real")
        monkeypatch.setattr(settings, "llm_providers", "gemini,groq")
        monkeypatch.setattr(settings, "gemini_api_key", "test-gemini-key")
        monkeypatch.setattr(settings, "gemini_model", "gemini-3.1-flash-lite")
        monkeypatch.setattr(settings, "groq_api_key", "test-groq-key")
        monkeypatch.setattr(settings, "groq_model", "llama-3.3-70b-versatile")
        monkeypatch.setattr(llm_client.time, "sleep", lambda s: None)

        # Mock Gemini to raise 429
        mock_gemini = MagicMock()
        mock_gemini.name = "gemini"
        mock_gemini.model = "gemini-3.1-flash-lite"
        mock_gemini.is_configured = True
        mock_gemini.generate_json.side_effect = RuntimeError("429 RESOURCE_EXHAUSTED: quota exceeded")

        # Mock Groq via httpx MockTransport
        def groq_handler(request: httpx.Request) -> httpx.Response:
            content = json.dumps({
                "choices": [{
                    "message": {"content": json.dumps({"finding_type": "NO_DISCREPANCY", "summary_narrative": "Groq OK"})}
                }],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            })
            return httpx.Response(200, content=content, headers={"Content-Type": "application/json"})

        mock_groq = OpenAICompatProvider(
            name="groq",
            base_url="https://api.groq.com/openai/v1",
            api_key="test-groq-key",
            model="llama-3.3-70b-versatile",
            transport=httpx.MockTransport(groq_handler),
        )

        def mock_get_provider(name):
            if name == "gemini":
                return mock_gemini
            if name == "groq":
                return mock_groq
            raise ValueError(name)

        monkeypatch.setattr(llm_client, "get_provider", mock_get_provider)

        raw_text, tokens = llm_client.call_llm("test prompt", "test instruction")
        assert "NO_DISCREPANCY" in raw_text
        assert tokens["provider"] == "groq"
        assert tokens["model"] == "llama-3.3-70b-versatile"
        assert tokens["total_tokens"] == 150
        # Gemini was retried once (2 calls total)
        assert mock_gemini.generate_json.call_count == 2
        # Attempts should record Gemini 429
        attempt_providers = [a["provider"] for a in tokens["attempts"]]
        assert "gemini" in attempt_providers

    def test_gemini_and_groq_fail_openrouter_success(self, monkeypatch):
        """Both Gemini and Groq fail (429 and 500); OpenRouter succeeds."""
        monkeypatch.setattr(settings, "llm_mode", "real")
        monkeypatch.setattr(settings, "llm_providers", "gemini,groq,openrouter")
        monkeypatch.setattr(settings, "gemini_api_key", "test-gemini-key")
        monkeypatch.setattr(settings, "gemini_model", "gemini-3.1-flash-lite")
        monkeypatch.setattr(settings, "groq_api_key", "test-groq-key")
        monkeypatch.setattr(settings, "groq_model", "llama-3.3-70b-versatile")
        monkeypatch.setattr(settings, "openrouter_api_key", "test-or-key")
        monkeypatch.setattr(settings, "openrouter_model", "google/gemini-2.0-flash-001")
        monkeypatch.setattr(llm_client.time, "sleep", lambda s: None)

        mock_gemini = MagicMock(name="gemini", model="gemini-3.1-flash-lite", is_configured=True)
        mock_gemini.name = "gemini"
        mock_gemini.model = "gemini-3.1-flash-lite"
        mock_gemini.generate_json.side_effect = RuntimeError("429 Rate limit exceeded")

        def groq_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "Internal Server Error"})

        mock_groq = OpenAICompatProvider(
            name="groq",
            base_url="https://api.groq.com/openai/v1",
            api_key="test-groq-key",
            model="llama-3.3-70b-versatile",
            transport=httpx.MockTransport(groq_handler),
        )

        def or_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "choices": [{"message": {"content": json.dumps({"finding_type": "NO_DISCREPANCY", "summary_narrative": "OpenRouter OK"})}}],
                "usage": {"prompt_tokens": 80, "completion_tokens": 40, "total_tokens": 120},
            })

        mock_or = OpenAICompatProvider(
            name="openrouter",
            base_url="https://openrouter.ai/api/v1",
            api_key="test-or-key",
            model="google/gemini-2.0-flash-001",
            transport=httpx.MockTransport(or_handler),
        )

        def mock_get_provider(name):
            if name == "gemini":
                return mock_gemini
            if name == "groq":
                return mock_groq
            if name == "openrouter":
                return mock_or
            raise ValueError(name)

        monkeypatch.setattr(llm_client, "get_provider", mock_get_provider)

        raw_text, tokens = llm_client.call_llm("test prompt", "test sys")
        assert "OpenRouter OK" in raw_text
        assert tokens["provider"] == "openrouter"
        assert tokens["model"] == "google/gemini-2.0-flash-001"
        assert tokens["total_tokens"] == 120

    def test_all_providers_fail_status_failed_audit_event_and_http_502(self, test_db_client, monkeypatch):
        """When all providers fail: returns HTTP 502, writes INVESTIGATION_RUN_FAILED event, 0 findings."""
        client, SessionLocal = test_db_client
        make_test_case(client)

        monkeypatch.setattr(settings, "llm_mode", "real")
        monkeypatch.setattr(settings, "llm_providers", "gemini,groq")
        monkeypatch.setattr(settings, "gemini_api_key", "test-gemini-key")
        monkeypatch.setattr(settings, "gemini_model", "gemini-3.1-flash-lite")
        monkeypatch.setattr(settings, "groq_api_key", "test-groq-key")
        monkeypatch.setattr(settings, "groq_model", "llama-3.3-70b-versatile")
        monkeypatch.setattr(llm_client.time, "sleep", lambda s: None)

        mock_gemini = MagicMock(name="gemini", model="gemini-3.1-flash-lite", is_configured=True)
        mock_gemini.name = "gemini"
        mock_gemini.model = "gemini-3.1-flash-lite"
        mock_gemini.generate_json.side_effect = RuntimeError("Gemini quota 429")

        mock_groq = MagicMock(name="groq", model="llama-3.3-70b-versatile", is_configured=True)
        mock_groq.name = "groq"
        mock_groq.model = "llama-3.3-70b-versatile"
        mock_groq.generate_json.side_effect = RuntimeError("Groq 500 Internal error")

        def mock_get_provider(name):
            if name == "gemini":
                return mock_gemini
            if name == "groq":
                return mock_groq
            raise ValueError(name)

        monkeypatch.setattr(llm_client, "get_provider", mock_get_provider)

        res = client.post(
            "/api/cases/case-resilience-1/investigations",
            headers=REVIEWER_HEADERS,
        )
        assert res.status_code == 502
        data = res.json()
        assert data["status"] == "FAILED"
        assert "run_id" in data
        assert "reason" in data
        assert "All LLM providers failed" in data["reason"]

        with SessionLocal() as db:
            # Deterministic calculation row must be persisted even though LLM providers failed
            calcs = db.query(Calculation).filter(Calculation.case_id == "case-resilience-1").all()
            assert len(calcs) == 1
            assert calcs[0].id is not None

            runs = db.query(InvestigationRun).filter(InvestigationRun.case_id == "case-resilience-1").all()
            assert len(runs) == 1
            assert runs[0].status == RunStatus.FAILED
            # No findings must be created for failed run
            findings = db.query(Finding).filter(Finding.case_id == "case-resilience-1").all()
            assert len(findings) == 0

            # Audit event must be written
            events = db.query(CaseEvent).filter(CaseEvent.case_id == "case-resilience-1").all()
            event_types = [e.event_type for e in events]
            assert "INVESTIGATION_RUN_FAILED" in event_types

            failed_event = [e for e in events if e.event_type == "INVESTIGATION_RUN_FAILED"][0]
            assert "actor" in failed_event.details
            assert "reason" in failed_event.details
            assert "attempts" in failed_event.details
            assert len(failed_event.details["attempts"]) > 0

    def test_invalid_json_falls_through_to_next_provider(self, monkeypatch):
        """Invalid JSON output from provider 1 causes immediate fallback to provider 2."""
        monkeypatch.setattr(settings, "llm_mode", "real")
        monkeypatch.setattr(settings, "llm_providers", "gemini,groq")
        monkeypatch.setattr(settings, "gemini_api_key", "test-gemini-key")
        monkeypatch.setattr(settings, "gemini_model", "gemini-3.1-flash-lite")
        monkeypatch.setattr(settings, "groq_api_key", "test-groq-key")
        monkeypatch.setattr(settings, "groq_model", "llama-3.3-70b-versatile")
        monkeypatch.setattr(llm_client.time, "sleep", lambda s: None)

        # Gemini returns non-JSON text
        mock_gemini = MagicMock(name="gemini", model="gemini-3.1-flash-lite", is_configured=True)
        mock_gemini.name = "gemini"
        mock_gemini.model = "gemini-3.1-flash-lite"
        mock_gemini.generate_json.return_value = (
            "I am an AI and I refuse to speak in JSON format.",
            {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            "gemini",
            "gemini-3.1-flash-lite",
        )

        mock_groq = MagicMock(name="groq", model="llama-3.3-70b-versatile", is_configured=True)
        mock_groq.name = "groq"
        mock_groq.model = "llama-3.3-70b-versatile"
        mock_groq.generate_json.return_value = (
            '{"finding_type": "NO_DISCREPANCY", "summary_narrative": "Groq Valid JSON"}',
            {"prompt_tokens": 50, "completion_tokens": 25, "total_tokens": 75},
            "groq",
            "llama-3.3-70b-versatile",
        )

        def mock_get_provider(name):
            if name == "gemini":
                return mock_gemini
            if name == "groq":
                return mock_groq
            raise ValueError(name)

        monkeypatch.setattr(llm_client, "get_provider", mock_get_provider)

        raw_text, tokens = llm_client.call_llm("test prompt", "test sys")
        assert "Groq Valid JSON" in raw_text
        assert tokens["provider"] == "groq"
        # Gemini was only called once (invalid JSON is not retried on same provider)
        assert mock_gemini.generate_json.call_count == 1
        assert any(a["error_type"] == "INVALID_JSON" for a in tokens["attempts"])

    def test_404_model_not_found_skipped_without_retry(self, monkeypatch):
        """Model 404 (Not Found) skips immediately to next provider with zero retry."""
        monkeypatch.setattr(settings, "llm_mode", "real")
        monkeypatch.setattr(settings, "llm_providers", "gemini,groq")
        monkeypatch.setattr(settings, "gemini_api_key", "test-gemini-key")
        monkeypatch.setattr(settings, "gemini_model", "deprecated-model-404")
        monkeypatch.setattr(settings, "groq_api_key", "test-groq-key")
        monkeypatch.setattr(settings, "groq_model", "llama-3.3-70b-versatile")
        monkeypatch.setattr(llm_client.time, "sleep", lambda s: None)

        mock_gemini = MagicMock(name="gemini", model="deprecated-model-404", is_configured=True)
        mock_gemini.name = "gemini"
        mock_gemini.model = "deprecated-model-404"
        mock_gemini.generate_json.side_effect = RuntimeError("404 NOT_FOUND: model deprecated-model-404 not found")

        mock_groq = MagicMock(name="groq", model="llama-3.3-70b-versatile", is_configured=True)
        mock_groq.name = "groq"
        mock_groq.model = "llama-3.3-70b-versatile"
        mock_groq.generate_json.return_value = (
            '{"finding_type": "NO_DISCREPANCY"}',
            {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            "groq",
            "llama-3.3-70b-versatile",
        )

        def mock_get_provider(name):
            if name == "gemini":
                return mock_gemini
            if name == "groq":
                return mock_groq
            raise ValueError(name)

        monkeypatch.setattr(llm_client, "get_provider", mock_get_provider)

        raw_text, tokens = llm_client.call_llm("test prompt", "test sys")
        assert tokens["provider"] == "groq"
        # 404 must NOT retry: exactly 1 attempt on Gemini
        assert mock_gemini.generate_json.call_count == 1
        assert any(a["error_type"] == "404_NOT_FOUND" for a in tokens["attempts"])

    def test_provider_without_key_or_model_is_skipped(self, monkeypatch):
        """Unconfigured provider (missing key or model) is cleanly skipped."""
        monkeypatch.setattr(settings, "llm_mode", "real")
        monkeypatch.setattr(settings, "llm_providers", "gemini,groq")
        # Gemini has no key
        monkeypatch.setattr(settings, "gemini_api_key", "")
        monkeypatch.setattr(settings, "gemini_model", "gemini-3.1-flash-lite")
        # Groq has key and model
        monkeypatch.setattr(settings, "groq_api_key", "test-groq-key")
        monkeypatch.setattr(settings, "groq_model", "llama-3.3-70b-versatile")

        mock_groq = MagicMock(name="groq", model="llama-3.3-70b-versatile", is_configured=True)
        mock_groq.name = "groq"
        mock_groq.model = "llama-3.3-70b-versatile"
        mock_groq.generate_json.return_value = (
            '{"finding_type": "NO_DISCREPANCY"}',
            {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            "groq",
            "llama-3.3-70b-versatile",
        )

        def mock_get_provider(name):
            if name == "gemini":
                return GeminiProvider(api_key="", model="gemini-3.1-flash-lite")
            if name == "groq":
                return mock_groq
            raise ValueError(name)

        monkeypatch.setattr(llm_client, "get_provider", mock_get_provider)

        raw_text, tokens = llm_client.call_llm("test prompt", "test sys")
        assert tokens["provider"] == "groq"
        assert mock_groq.generate_json.call_count == 1

    def test_response_format_rejected_retry_without_it_succeeds(self):
        """If provider returns HTTP 400 mentioning response_format, retry without it succeeds."""
        call_count = {"calls": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["calls"] += 1
            body = json.loads(request.read())
            if "response_format" in body:
                return httpx.Response(400, text='{"error": "response_format is not supported by this model"}')
            # Fallback without response_format succeeds and returns json in markdown fences
            return httpx.Response(
                200,
                json={
                    "choices": [{
                        "message": {"content": "```json\n{\"finding_type\": \"NO_DISCREPANCY\", \"notes\": \"parsed\"}\n```"}
                    }],
                    "usage": {"prompt_tokens": 40, "completion_tokens": 20, "total_tokens": 60},
                },
            )

        provider = OpenAICompatProvider(
            name="groq",
            base_url="https://api.groq.com/openai/v1",
            api_key="test-key",
            model="custom-model",
            transport=httpx.MockTransport(handler),
        )

        text, tokens, p_name, model = provider.generate_json("sys", "prompt")
        assert call_count["calls"] == 2
        parsed = json.loads(text)
        assert parsed["finding_type"] == "NO_DISCREPANCY"
        assert tokens["total_tokens"] == 60

    def test_keys_never_appear_in_logs_errors_status_or_token_usage(self, test_db_client, monkeypatch, caplog):
        """Strict secret isolation: API keys are redacted from logs, exceptions, status, and DB."""
        client, SessionLocal = test_db_client
        make_test_case(client)

        secret_gemini = "AIzaSySecretGeminiKeyNineZeroZeroOne"
        secret_groq = "gsk_superSecretGroqKeyAlphaBravo12345"
        secret_or = "sk-or-v1-superSecretOpenRouterKey998877"

        monkeypatch.setattr(settings, "llm_mode", "real")
        monkeypatch.setattr(settings, "llm_providers", "gemini,groq,openrouter")
        monkeypatch.setattr(settings, "gemini_api_key", secret_gemini)
        monkeypatch.setattr(settings, "gemini_model", "gemini-3.1-flash-lite")
        monkeypatch.setattr(settings, "groq_api_key", secret_groq)
        monkeypatch.setattr(settings, "groq_model", "llama-3.3-70b-versatile")
        monkeypatch.setattr(settings, "openrouter_api_key", secret_or)
        monkeypatch.setattr(settings, "openrouter_model", "google/gemini-2.0-flash-001")
        monkeypatch.setattr(llm_client.time, "sleep", lambda s: None)

        mock_gemini = MagicMock(name="gemini", model="gemini-3.1-flash-lite", is_configured=True)
        mock_gemini.name = "gemini"
        mock_gemini.model = "gemini-3.1-flash-lite"
        mock_gemini.generate_json.side_effect = RuntimeError(f"Auth failed with {secret_gemini}")

        mock_groq = MagicMock(name="groq", model="llama-3.3-70b-versatile", is_configured=True)
        mock_groq.name = "groq"
        mock_groq.model = "llama-3.3-70b-versatile"
        mock_groq.generate_json.side_effect = RuntimeError(f"Bearer {secret_groq} expired")

        mock_or = MagicMock(name="openrouter", model="google/gemini-2.0-flash-001", is_configured=True)
        mock_or.name = "openrouter"
        mock_or.model = "google/gemini-2.0-flash-001"
        mock_or.generate_json.side_effect = RuntimeError(f"OpenRouter key {secret_or} unauthorized")

        def mock_get_provider(name):
            if name == "gemini":
                return mock_gemini
            if name == "groq":
                return mock_groq
            if name == "openrouter":
                return mock_or
            raise ValueError(name)

        monkeypatch.setattr(llm_client, "get_provider", mock_get_provider)

        with caplog.at_level(logging.DEBUG):
            res = client.post("/api/cases/case-resilience-1/investigations", headers=REVIEWER_HEADERS)
            assert res.status_code == 502
            data = res.json()

        # 1. Check API response body
        res_str = json.dumps(data)
        assert secret_gemini not in res_str
        assert secret_groq not in res_str
        assert secret_or not in res_str

        # 2. Check /api/llm/status
        status_res = client.get("/api/llm/status", headers=VIEWER_HEADERS)
        assert status_res.status_code == 200
        status_str = json.dumps(status_res.json())
        assert secret_gemini not in status_str
        assert secret_groq not in status_str
        assert secret_or not in status_str

        # 3. Check DB token_usage and CaseEvent
        with SessionLocal() as db:
            run = db.query(InvestigationRun).filter(InvestigationRun.case_id == "case-resilience-1").first()
            if run and run.token_usage:
                tu_str = json.dumps(run.token_usage)
                assert secret_gemini not in tu_str
                assert secret_groq not in tu_str
                assert secret_or not in tu_str

            events = db.query(CaseEvent).filter(CaseEvent.case_id == "case-resilience-1").all()
            for ev in events:
                ev_str = json.dumps(ev.details)
                assert secret_gemini not in ev_str
                assert secret_groq not in ev_str
                assert secret_or not in ev_str

        # 4. Check logs
        all_logs = caplog.text
        assert secret_gemini not in all_logs
        assert secret_groq not in all_logs
        assert secret_or not in all_logs

    def test_get_llm_status_endpoint(self, test_db_client, monkeypatch):
        """GET /api/llm/status returns configured (bool) and model per provider for any role."""
        client, _ = test_db_client

        monkeypatch.setattr(settings, "llm_providers", "gemini,groq,openrouter")
        monkeypatch.setattr(settings, "gemini_api_key", "gem-key")
        monkeypatch.setattr(settings, "gemini_model", "gemini-3.1-flash-lite")
        monkeypatch.setattr(settings, "groq_api_key", "")
        monkeypatch.setattr(settings, "groq_model", "llama-3.3-70b-versatile")
        monkeypatch.setattr(settings, "openrouter_api_key", "")
        monkeypatch.setattr(settings, "openrouter_model", "")

        # Unauthenticated rejected
        unauth = client.get("/api/llm/status")
        assert unauth.status_code in (401, 403)

        # Authenticated as VIEWER
        res = client.get("/api/llm/status", headers=VIEWER_HEADERS)
        assert res.status_code == 200
        data = res.json()
        assert data["gemini"]["configured"] is True
        assert data["gemini"]["model"] == "gemini-3.1-flash-lite"
        assert data["groq"]["configured"] is False
        assert data["openrouter"]["configured"] is False
