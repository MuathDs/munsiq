"""OpenAI-compatible inference client.

Points at ``settings.INFERENCE_BASE_URL`` — Ollama locally. Written against the
OpenAI wire format so the endpoint can move to vLLM later with a URL change and
no code change.

Ollama is a development choice, not a production one: it has no built-in
authentication and its throughput flattens at a handful of concurrent requests.
Anything multi-user belongs behind vLLM with continuous batching.

The model is ``settings.INFERENCE_MODEL``, default ``qwen2.5:7b-instruct`` — a
general instruct model, NOT the munsiq-extractor fine-tune. That fine-tune has a
fixed five-column schema baked into its weights; this phase passes the field
list in the prompt at runtime instead. Using it would defeat the design.
"""

from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class InferenceError(Exception):
    """The model endpoint failed or returned something unusable."""


@dataclass
class ChatResult:
    content: str
    model: str
    latency_ms: int

    def as_json(self) -> dict[str, Any]:
        """Parse the content as JSON, tolerating a fenced code block.

        Model output is untrusted: a parse failure is an error to report, never
        something to paper over with a regex salvage attempt.
        """
        text = self.content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            text = text.rsplit("```", 1)[0]
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise InferenceError(f"model did not return valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise InferenceError(f"model returned {type(parsed).__name__}, expected an object")
        return parsed


class InferenceClient(Protocol):
    def chat(
        self, *, system: str, user: str, images: list[bytes] | None = None, json_mode: bool = True
    ) -> ChatResult: ...


class OllamaClient:
    """Minimal OpenAI-compatible chat client with jittered retries."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout_s: float | None = None,
        max_retries: int | None = None,
    ) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.INFERENCE_BASE_URL).rstrip("/")
        self.model = model or settings.INFERENCE_MODEL
        self.timeout_s = timeout_s or settings.INFERENCE_TIMEOUT_S
        self.max_retries = settings.INFERENCE_MAX_RETRIES if max_retries is None else max_retries

    def chat(
        self, *, system: str, user: str, images: list[bytes] | None = None, json_mode: bool = True
    ) -> ChatResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            # Temperature 0: extraction is not a creative task, and a stable
            # output is what makes a regression measurable.
            "temperature": 0,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if images:
            # Vision path is opt-in and untested at 4GB; the shape is here so
            # enabling it is a config change rather than a rewrite.
            payload["messages"][1] = _with_images(user, images)

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            started = time.monotonic()
            try:
                with httpx.Client(timeout=self.timeout_s) as client:
                    response = client.post(f"{self.base_url}/chat/completions", json=payload)
                    response.raise_for_status()
                    body = response.json()
                content = body["choices"][0]["message"]["content"]
                return ChatResult(
                    content=content,
                    model=body.get("model", self.model),
                    latency_ms=int((time.monotonic() - started) * 1000),
                )
            except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    backoff = (2**attempt) + random.uniform(0, 0.5)
                    logger.warning(
                        "inference.retry",
                        extra={"attempt": attempt + 1, "backoff_s": round(backoff, 2)},
                    )
                    time.sleep(backoff)

        raise InferenceError(
            f"inference failed after {self.max_retries + 1} attempts: {last_error}"
        ) from last_error


def _with_images(text: str, images: list[bytes]) -> dict[str, Any]:
    import base64

    parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for image in images:
        encoded = base64.b64encode(image).decode("ascii")
        parts.append(
            {"type": "image_url", "image_url": {"url": f"data:image/webp;base64,{encoded}"}}
        )
    return {"role": "user", "content": parts}
