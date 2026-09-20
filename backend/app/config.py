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
    # Role the application drops to for every request transaction, via
    # SET LOCAL ROLE. Supabase's `postgres` carries BYPASSRLS, so without this
    # the app's own queries are not constrained by RLS at all. `authenticated`
    # is provisioned by Supabase and has neither superuser nor BYPASSRLS.
    # Set to "" to disable the switch (only correct if DATABASE_URL already
    # points at a non-bypassing role). Migrations never use this — see
    # app/db/session.py.
    DB_APP_ROLE: str = "authenticated"

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
    # changes. Never hardcode a model URL anywhere else — see CLAUDE.md.
    INFERENCE_BASE_URL: str = "http://localhost:11434/v1"

    # A general instruct model, NOT the munsiq-extractor fine-tune. That model
    # has a fixed 5-column schema baked into its weights, which is precisely the
    # approach this phase replaces: the field list is passed in the prompt at
    # runtime, read from extraction_schemas.definition. Pointing this at
    # munsiq-extractor would defeat the whole design.
    INFERENCE_MODEL: str = "qwen2.5:7b-instruct"
    INFERENCE_TIMEOUT_S: float = 180.0
    INFERENCE_MAX_RETRIES: int = 2

    # Vision path is opt-in. A VL model does not fit comfortably in 4GB, so the
    # default sends OCR/text-layer text only.
    EXTRACTION_USE_VISION: bool = False

    MAX_UPLOAD_BYTES: int = 25 * 1024 * 1024

    # ----------------------------------------------------------------- #
    # Storage — local filesystem. The Storage protocol keeps S3 swappable,
    # but the S3 implementation is deliberately not built in this phase.
    # ----------------------------------------------------------------- #
    STORAGE_DIR: str = "var/storage"
    MAX_PAGES: int = 50
    RASTER_DPI: int = 150
    WEBP_QUALITY: int = 85

    # ----------------------------------------------------------------- #
    # Text extraction
    # ----------------------------------------------------------------- #
    # OCR runs ONLY on pages with no embedded text layer. "rapidocr" | "none".
    OCR_ENGINE: str = "rapidocr"

    # rapidfuzz score below which an extracted value counts as ungrounded.
    GROUNDING_THRESHOLD: int = 85

    # ----------------------------------------------------------------- #
    # Signed page-image URLs
    # ----------------------------------------------------------------- #
    # HMAC key for page-image tokens. MUST be set outside local development:
    # an empty key would make every page image readable across tenants. Local
    # dev generates a random per-process key instead of defaulting to anything
    # guessable. See app/services/signed_urls.py.
    IMAGE_URL_SECRET: str = ""

    # Page-image URLs expire fast. They authorize by signature rather than by
    # session, so a long life turns a leaked URL into a standing grant.
    PAGE_URL_TTL_S: int = 300

    # Upload authorizations expire just as fast, and for the same reason: the
    # token is a standing grant to write documents into one tenant while it lives.
    UPLOAD_URL_TTL_S: int = 300

    # A document with no annotation this long after upload is reported as
    # 'stalled' instead of 'processing'. The pipeline runs in a background task
    # with no retries (see CLAUDE.md), so a process that died mid-document would
    # otherwise look like it is still working, forever. The model path took ~3
    # minutes on this machine; this leaves generous headroom.
    STALLED_AFTER_S: int = 900

    # ----------------------------------------------------------------- #
    # Trusted BFF — a scaffold for deferred authentication
    # ----------------------------------------------------------------- #
    # Real auth (JWT) is deferred. Until it lands, the Next.js BFF holds the
    # org identity server-side and asserts it to this API. Accepting such an
    # assertion is only safe when the caller proves it is the BFF, so BOTH of
    # these must be set: the flag opts in, the secret authenticates.
    #
    # Off by default, and the secret has no default. With either unset,
    # get_current_org_id raises 501 exactly as before — a browser can never
    # choose its own tenant. See app/api/deps.py.
    TRUSTED_BFF_ENABLED: bool = False
    TRUSTED_BFF_SECRET: str = ""

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
