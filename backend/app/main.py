"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Aliased: a bare `annotations` import would shadow `from __future__ import
# annotations` above, which mypy flags and which would confuse any reader.
from app.api import annotations as annotations_api
from app.api import documents, health, pages, uploads
from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup and shutdown.

    Nothing to open in Phase 1 — no database, no queue, no inference client.
    The hook exists so Phase 2 has a place to put the engine without touching
    the factory's shape.
    """
    settings = get_settings()
    logger.info(
        "startup",
        extra={"environment": settings.ENVIRONMENT, "debug_endpoints": settings.DEBUG_ENDPOINTS},
    )
    yield
    logger.info("shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application.

    Args:
        settings: Injected for tests, which need to flip DEBUG_ENDPOINTS without
            mutating the process-wide singleton.
    """
    settings = settings or get_settings()

    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        summary="Document information extraction for Arabic/English invoices (ZATCA).",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix=settings.API_V1_PREFIX)
    app.include_router(annotations_api.router, prefix=settings.API_V1_PREFIX)
    app.include_router(uploads.router, prefix=settings.API_V1_PREFIX)
    # Signed-token route: authorization travels in the URL, so it is not behind
    # the tenant session dependency. See app/api/pages.py.
    app.include_router(pages.router, prefix=settings.API_V1_PREFIX)

    if settings.DEBUG_ENDPOINTS:
        # Registered conditionally: /documents/probe accepts unauthenticated
        # uploads. See app/api/documents.py for the full warning.
        logger.warning("debug_endpoints_enabled", extra={"routes": ["/documents/probe"]})
        app.include_router(documents.router, prefix=settings.API_V1_PREFIX)

    return app


app = create_app()
