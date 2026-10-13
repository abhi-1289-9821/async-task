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

    # ── AI (Phase 3) ──────────────────────────────────────────────────────────
    # GEMINI_API_KEY must be set before Phase 3. LLM_MODE=mock bypasses it in tests.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"  # Verified Gemini model
    llm_mode: str = "real"                  # "mock" for automated tests; "real" for live

    # ── Auth (demo only) ──────────────────────────────────────────────────────
    # Two tokens map to REVIEWER and VIEWER roles.
    # In production, default tokens are strictly disallowed by validator below.
    demo_reviewer_token: str = "demo-reviewer-token-change-me"
    demo_viewer_token: str = "demo-viewer-token-change-me"

    # ── App ───────────────────────────────────────────────────────────────────
    debug: bool = False
    app_version: str = "0.1.0"
    cors_origins: str = "http://localhost:5173"  # comma-separated for prod

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        """
        Hard security barrier:
        Refuses to start application in production if default demo tokens are unchanged.
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
            if not self.gemini_api_key or self.gemini_api_key in ("your-gemini-api-key-here", "your_gemini_api_key_here"):
                raise ValueError(
                    "Production Security Error: GEMINI_API_KEY must be set in production when LLM_MODE=real."
                )
        return self


settings = Settings()
