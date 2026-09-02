"""Liveness and readiness endpoints."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import Settings, get_settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    app_name: str
    environment: str


@router.get("/health", summary="Liveness probe")
def health() -> HealthResponse:
    """Return process health. No dependencies are touched, so this stays fast."""
    settings: Settings = get_settings()
    return HealthResponse(
        status="ok",
        app_name=settings.APP_NAME,
        environment=settings.ENVIRONMENT,
    )
