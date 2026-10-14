"""
config.py
=========
Application settings loaded from environment variables via pydantic-settings.
All sensitive values come from environment; .env file used for local dev.
Never commit .env. Use .env.example as the template.
"""

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

    gemini_api_key: str = ""
    gemini_model: str = ""

    groq_api_key: str = ""
    groq_model: str = ""

    openrouter_api_key: str = ""
    openrouter_model: str = ""

    # Two tokens map to REVIEWER and VIEWER roles.
    # In production, default tokens are strictly disallowed by validator below.
    demo_reviewer_token: str = "demo-reviewer-token-change-me"
    demo_viewer_token: str = "demo-viewer-token-change-me"
    # Optional multi-user tokens: "token_alice:alice@acmebilling.com,token_bob:bob@acmebilling.com"
    reviewer_tokens: str = ""

    # ── App ───────────────────────────────────────────────────────────────────
    debug: bool = False
    app_version: str = "0.1.0"
    cors_origins: str = "http://localhost:5173"  # comma-separated for prod

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        """
        Hard security barrier:
        Refuses to start application in production if default demo tokens are unchanged,
        or if LLM_MODE is mock, or if no LLM provider is fully configured.
        """
        if self.environment.lower() == "production":
            default_token = "demo-reviewer-token-change-me"
            default_viewer = "demo-viewer-token-change-me"
            if (
                self.demo_reviewer_token == default_token
                or self.demo_viewer_token == default_viewer
                or not self.demo_reviewer_token
                or not self.demo_viewer_token
            ):
                raise ValueError(
                    "Production Security Error: Application refuses to start with default demo tokens. "
                    "When ENVIRONMENT=production, DEMO_REVIEWER_TOKEN and DEMO_VIEWER_TOKEN must be "
                    "explicitly set to non-default secure values."
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
