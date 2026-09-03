"""Application settings.

Every runtime knob lives here and is read from the environment via
pydantic-settings. No module anywhere else in the backend may hardcode a URL,
a credential or a feature flag — see CLAUDE.md, "No secrets in code".
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Backend configuration, loaded from backend/.env and the process environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    APP_NAME: str = "Munsiq API"
    ENVIRONMENT: Literal["local", "dev", "prod"] = "local"
    API_V1_PREFIX: str = "/api/v1"

    # PostgreSQL DSN. Supabase hands out a `postgresql://` URL; we normalize it
    # to the asyncpg driver below so either form works in .env.
    DATABASE_URL: str = ""
    DB_ECHO: bool = False
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 5

    CORS_ORIGINS: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # Registers temporary, UNAUTHENTICATED debug routes (currently the document
    # probe). Defaults to False so it is opt-in per environment, never on by
    # accident in anything network-reachable.
    DEBUG_ENDPOINTS: bool = False

    # OpenAI-compatible inference endpoint. Ollama locally; the client is written
    # against the OpenAI wire format so the endpoint can be swapped without code
    # changes. Unused in Phase 1 — declared now so no module invents its own
    # constant later (see CLAUDE.md, "Deprecated paths").
    INFERENCE_BASE_URL: str = "http://localhost:11434/v1"
    INFERENCE_MODEL: str = "munsiq-extractor"

    MAX_UPLOAD_BYTES: int = 25 * 1024 * 1024

    @property
    def async_database_url(self) -> str:
        """DATABASE_URL forced onto the asyncpg driver.

        Supabase's dashboard gives out `postgresql://...`, which SQLAlchemy would
        route to psycopg. Normalizing here means .env can hold either form and
        nothing downstream has to care.
        """
        url = self.DATABASE_URL
        if url.startswith("postgresql+"):
            return url
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+asyncpg://", 1)
        return url

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept a comma-separated string as well as a JSON list."""
        if isinstance(value, str) and not value.strip().startswith("["):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide Settings singleton."""
    return Settings()
