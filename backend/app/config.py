"""
config.py
=========
Application settings loaded from environment variables via pydantic-settings.
All sensitive values come from environment; .env file used for local dev.
Never commit .env. Use .env.example as the template.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = "sqlite:///./billing_disputes.db"

    # ── AI (Phase 3) ──────────────────────────────────────────────────────────
    # GEMINI_API_KEY must be set before Phase 3. LLM_MODE=mock bypasses it in tests.
    gemini_api_key: str = ""
    gemini_model: str = ""          # e.g. "gemini-2.0-flash" — set via env, never hardcoded
    llm_mode: str = "real"          # "mock" for automated tests only; "real" for production

    # ── Auth (demo only) ──────────────────────────────────────────────────────
    # Two fixed tokens map to REVIEWER and VIEWER roles.
    # This is NOT production auth. See README security disclaimer.
    demo_reviewer_token: str = "demo-reviewer-token-change-me"
    demo_viewer_token: str = "demo-viewer-token-change-me"

    # ── App ───────────────────────────────────────────────────────────────────
    debug: bool = False
    app_version: str = "0.1.0"
    cors_origins: str = "http://localhost:5173"  # comma-separated for prod


settings = Settings()
