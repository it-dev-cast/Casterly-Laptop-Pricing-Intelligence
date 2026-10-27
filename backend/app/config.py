"""Environment configuration. Every setting is read from CLPI_* environment variables."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CLPI_", env_file=".env", extra="ignore")

    environment: str = "development"
    database_url: str = "postgresql+psycopg2://clpi:clpi@localhost:5432/clpi"

    # Auth
    secret_key: str = Field(default="change-me-in-production-please-32+chars", min_length=16)
    token_ttl_minutes: int = 480
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None
    bootstrap_admin_name: str = "Administrator"

    # File handling
    upload_dir: Path = Path("./data/uploads")
    max_upload_mb: int = 10
    max_upload_rows: int = 20000
    max_xlsx_uncompressed_mb: int = 100

    # Optional Claude integration. The application is fully functional without it.
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5-5"
    ai_timeout_seconds: float = 60.0

    # Pricing Intelligence market research (licensed search APIs only; keys stay on the server)
    brave_api_key: str | None = None
    tavily_api_key: str | None = None
    research_provider: str | None = None  # brave | tavily; default = first configured
    research_http_timeout: float = 20.0
    research_worker: str = "thread"  # thread = in-process background worker; off = run `python -m app.procurement.worker`
    research_poll_seconds: float = Field(3.0, gt=0)
    reference_dirs: list[Path] = []
    approved_catalog_path: Path | None = None
    approved_catalog_terms_confirmed: bool = False

    # CORS (the Vite dev server); the Docker build serves the UI from the same origin.
    cors_origins: list[str] = ["http://localhost:5180", "http://127.0.0.1:5180"]

    @field_validator("approved_catalog_path", mode="before")
    @classmethod
    def empty_catalog(cls, value):
        return None if value == "" else value

    @model_validator(mode="after")
    def validate_production(self):
        if self.environment.lower() == "production" and (len(self.secret_key) < 32 or self.secret_key.startswith("change-me")):
            raise ValueError("Production requires CLPI_SECRET_KEY with at least 32 random characters")
        if self.research_worker not in ("thread", "off"):
            raise ValueError("CLPI_RESEARCH_WORKER must be thread or off")
        return self

    @property
    def ai_configured(self) -> bool:
        return bool(self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
