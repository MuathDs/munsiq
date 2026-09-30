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

    # Ollama's own origin — NO trailing /v1. The client calls its native
    # /api/chat, not the OpenAI-compatible endpoint: verified against Ollama
    # 0.34.1, the OpenAI-compatible endpoint silently ignores `think`, and a
    # hybrid-reasoning model (qwen3.5) then never stops thinking regardless of
    # what is sent — see extraction/client.py's module docstring. Never
    # hardcode a model URL anywhere else — see CLAUDE.md.
    INFERENCE_BASE_URL: str = "http://localhost:11434"

    # A general instruct model, NOT the munsiq-extractor fine-tune. That model
    # has a fixed 5-column schema baked into its weights, which is precisely the
    # approach this phase replaces: the field list is passed in the prompt at
    # runtime, read from extraction_schemas.definition. Pointing this at
    # munsiq-extractor would defeat the whole design.
    INFERENCE_MODEL: str = "qwen2.5:7b-instruct"
    INFERENCE_TIMEOUT_S: float = 180.0

    # Sent with every request. Greedy decoding (temperature 0) does not depend on
    # it, so it changes nothing today; it is pinned so that turning sampling on
    # later cannot make runs unrepeatable without anyone noticing.
    INFERENCE_SEED: int = 0

    # The context window requested on every call, via native /api/chat's
    # options.num_ctx — which Ollama actually honours (checked directly: a
    # small num_ctx measurably truncates prompt_eval_count). This was NOT true
    # of the OpenAI-compatible endpoint this client used before 2026-09-24,
    # which silently ignored num_ctx altogether (verified against Ollama
    # 0.34.1) — the same silent-ignore shape `think` turned out to have there
    # too, which is why the client no longer uses that endpoint at all. Still
    # matched to what this 4 GB GPU can actually hold: raising it without more
    # VRAM does not add context, it OOMs. The post-hoc guard below stays as a
    # correctness backstop, not the primary mechanism — a chat template's own
    # overhead could still in principle push a request over the requested
    # window.
    INFERENCE_NUM_CTX: int = 4096
    INFERENCE_MAX_RETRIES: int = 2

    # "text": every page as text, however degraded. "vision": every page as an
    # image, however clean its text is — the forced comparison arm. "auto"
    # (the default): per page, by app/services/extraction/routing.py — a clean
    # text layer stays on the cheap, exact text path; a page with no usable
    # text or a text layer that looks cut apart is read as an image instead.
    # Step Zero (signed UBL) always wins regardless of this setting — the model
    # is not called at all when the invoice already told us the answer.
    EXTRACTION_MODE: Literal["text", "vision", "auto"] = "auto"

    # Deliberately a SEPARATE model, base URL and context size from the text
    # settings above, not a flag on the same client: a heavier VL model
    # (qwen2.5vl:7b, say) belongs on a machine with more VRAM — a Colab
    # notebook tunnelled through ngrok, for instance — which is exactly what
    # VISION_INFERENCE_BASE_URL is for. Falls back to INFERENCE_BASE_URL when
    # unset, so a local-only setup needs to configure nothing extra.
    #
    # qwen2.5vl:3b (the vision-only VL model tried first) scored 7/9 on the one
    # real invoice tested by hand, both errors confined to the totals block.
    # qwen3.5:4b — Apache 2.0, checked via `ollama show qwen3.5:4b` before
    # adopting it — is a hybrid-reasoning model with BOTH vision and completion
    # capability (`ollama show` lists ["completion","vision","tools",
    # "thinking"]), and beat it on the same invoice, same bare prompt: 8/9,
    # only one dropped word in a name — but only once temperature, seed and
    # think were all sent explicitly (see extraction/client.py). At Ollama's
    # own defaults for it (temperature 1, thinking on) it scored 3/9 with
    # invented computed values, on the SAME prompt. Also fits the same 4 GB
    # card.
    VISION_MODEL: str = "qwen3.5:4b"
    VISION_INFERENCE_BASE_URL: str | None = None
    VISION_NUM_CTX: int = 4096
    """Requested via options.num_ctx on every call — see INFERENCE_NUM_CTX's
    own comment for why that is now authoritative rather than hoped-for. An
    image costs real context — measured on this box, a single page at
    VISION_RASTER_DPI=100 is ~1,300 prompt tokens before the field guidelines
    are even added — so this is checked separately from the text path's
    budget, and independently configurable for a remote model that may be
    given a larger window."""

    # Lower than RASTER_DPI (150, for the review UI's own page image): a vision
    # model's prompt cost scales with pixel count, not just file size — the
    # SAME page measured at 150 DPI cost 2.8x the prompt tokens of 100 DPI on
    # this model. 100 DPI answered every field correctly in that comparison and
    # leaves headroom in a 4096-token window for the schema-conditioned prompt
    # (field guidelines) alongside it.
    VISION_RASTER_DPI: int = 100

    # However many pages classify as needing vision, at most this many are
    # actually attached as images to one call — each one costs real context
    # against VISION_NUM_CTX, and the inference client fails loudly rather
    # than silently truncating (see extraction/client.py); this cap exists so
    # a five-page unreadable scan fails predictably instead of via a
    # token-budget accident.
    MAX_VISION_PAGES: int = 2

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

    # Read the ZATCA QR printed on the page (app/services/qr.py) when there is no
    # embedded XML: seller name, seller VAT number, date, total and VAT come from
    # it deterministically and outrank the model. Local only — OpenCV, already
    # installed with RapidOCR. Off is the control arm for measuring it.
    QR_READING: bool = True
    # Higher than RASTER_DPI on purpose: a receipt's QR can be ~2.5 cm across
    # with ~80 modules, which is about 2 px per module at 150 DPI — too few to
    # decode. 300 DPI gives ~4.
    QR_RASTER_DPI: int = 300

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
