"""
config.py
=========
Application settings loaded from environment variables via pydantic-settings.
All sensitive values come from environment; .env file used for local dev.
Never commit .env. Use .env.example as the template.
"""

from typing import Any
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Environment ───────────────────────────────────────────────────────────
    environment: str = "development"

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = "sqlite:///./billing_disputes.db"

    # ── AI / LLM Providers ───────────────────────────────────────────────────
    llm_providers: str = "gemini,groq,openrouter"  # ordered, comma-separated fallback list
    llm_mode: str = "real"                        # "mock" for automated tests; "real" for live investigations
    allow_mock_fallback: bool = True

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    openrouter_api_key: str = ""
    openrouter_model: str = "google/gemini-2.5-flash"

    # Two tokens map to REVIEWER and VIEWER roles.
    # In strict production (demo_mode=false), default demo tokens are refused.
    demo_mode: bool = False
    demo_reviewer_token: str = "demo-reviewer-token-2026"
    demo_viewer_token: str = "demo-viewer-token-2026"
    # Optional multi-user tokens: "token_alice:alice@fairbill.io,token_bob:bob@fairbill.io"
    reviewer_tokens: str = ""

    # ── App ───────────────────────────────────────────────────────────────────
    debug: bool = False
    app_version: str = "0.1.0"
    cors_origins: str = "http://localhost:5173"  # comma-separated for prod
    investigation_run_ttl_seconds: int = 180

    @model_validator(mode="before")
    @classmethod
    def apply_env_defaults(cls, data: Any) -> Any:
        if isinstance(data, dict):
            env = str(data.get("environment", "development")).lower()
            if "demo_mode" not in data or data.get("demo_mode") is None:
                # Default off in production, default on in dev/test
                data["demo_mode"] = False if env == "production" else True
        return data

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        """
        Hard security barrier:
        Refuses to start application in production if default demo tokens are unchanged when demo_mode=false,
        or if LLM_MODE is mock, or if no LLM provider is fully configured.
        """
        if self.environment.lower() == "production":
            if not self.demo_reviewer_token or not self.demo_viewer_token:
                raise ValueError(
                    "Production Security Error: Application requires DEMO_REVIEWER_TOKEN and DEMO_VIEWER_TOKEN to be set."
                )
            if not self.demo_mode:
                default_tokens = ("demo-reviewer-token-2026", "demo-viewer-token-2026")
                if self.demo_reviewer_token in default_tokens or self.demo_viewer_token in default_tokens:
                    raise ValueError(
                        "Production Security Error: Default evaluation tokens are strictly forbidden when DEMO_MODE=false in production."
                    )
            if self.llm_mode.lower() == "mock":
                raise ValueError(
                    "Production Security Error: LLM_MODE cannot be 'mock' in production."
                )

            # Enforce at least one fully configured provider
            placeholder_keys = (
                "your-gemini-api-key-here", "your_gemini_api_key_here",
                "your-groq-api-key-here", "your_groq_api_key_here",
                "your-openrouter-api-key-here", "your_openrouter_api_key_here",
            )
            has_configured_provider = False
            if self.gemini_api_key and self.gemini_api_key not in placeholder_keys and self.gemini_model:
                has_configured_provider = True
            if self.groq_api_key and self.groq_api_key not in placeholder_keys and self.groq_model:
                has_configured_provider = True
            if self.openrouter_api_key and self.openrouter_api_key not in placeholder_keys and self.openrouter_model:
                has_configured_provider = True

            if not has_configured_provider:
                raise ValueError(
                    "Production Security Error: At least one LLM provider (Gemini, Groq, or OpenRouter) "
                    "must be fully configured with a valid API key and model when ENVIRONMENT=production."
                )
        return self


settings = Settings()
