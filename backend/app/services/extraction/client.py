"""Ollama's native inference client.

Points at ``settings.INFERENCE_BASE_URL`` (Ollama's own origin, e.g.
``http://localhost:11434`` — no ``/v1``) and calls ``/api/chat``, NOT the
OpenAI-compatible ``/v1/chat/completions``. This was deliberately the OpenAI
wire format until 2026-09-24, so the endpoint could move to vLLM later with a
URL change and no code change. That stopped being safe to keep: verified
against Ollama 0.34.1, the ``/v1`` endpoint silently accepts and ignores
``think`` — a hybrid-reasoning model (qwen3.5, family ``qwen35``) keeps
thinking regardless of what is sent, exactly the same failure shape as
``INFERENCE_NUM_CTX`` (also silently ignored over ``/v1``, see config.py).
The native endpoint honours ``think`` correctly (checked directly: identical
request through `/api/chat` with ``think: false`` returns no reasoning at all
and a fraction of the completion tokens). A hybrid-reasoning model that never
stops thinking is not a config nuance here — it burns the context budget on
prose the JSON parser never sees, which is the exact class of bug this
codebase treats as a correctness bug, not a latency one.

Losing the trivial vLLM swap is the accepted cost. vLLM's OpenAI-compatible
endpoint has its own (different) way to disable Qwen3 thinking
(``chat_template_kwargs: {"enable_thinking": false}``), so that swap was never
truly a "URL change and no code change" for a thinking model anyway.

Ollama is a development choice, not a production one: it has no built-in
authentication and its throughput flattens at a handful of concurrent requests.
Anything multi-user belongs behind vLLM with continuous batching.

The model is ``settings.INFERENCE_MODEL``, default ``qwen2.5:7b-instruct`` — a
general instruct model, NOT the munsiq-extractor fine-tune. That fine-tune has a
fixed five-column schema baked into its weights; this phase passes the field
list in the prompt at runtime instead. Using it would defeat the design.

Every call sends temperature, seed and think EXPLICITLY — never relying on the
server's defaults. qwen3.5 defaults to temperature 1 in Ollama (checked via
``/api/show``), which alone turned a manual 8/9-correct read into 3/9 with
invented values. ``test_inference_client.py`` asserts these three are present
and correct on every call, images or not, json_mode or not.
"""

from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass
from typing import Any, Final, Protocol

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class InferenceError(Exception):
    """The model endpoint failed or returned something unusable."""


# Cloudflare's "A timeout occurred": its free quick tunnel (trycloudflare.com)
# closes any request still unanswered after 100 seconds, while the origin keeps
# generating. Not an Ollama status — only a tunnel in front of it sends this.
CLOUDFLARE_TIMEOUT: Final = 524
CLOUDFLARE_TIMEOUT_S: Final = 100


def _tunnel_timeout_message(base_url: str) -> str:
    host = httpx.URL(base_url).host
    return (
        f"The inference server at {host} did not answer in time (HTTP 524): the "
        f"Cloudflare tunnel in front of it closes a request after "
        f"{CLOUDFLARE_TIMEOUT_S} seconds, and this one took longer. Not retried — the "
        "same prompt would take as long again. Use a smaller model or fewer pages, or "
        "reach the server without the tunnel's limit."
    )


@dataclass
class ChatResult:
    content: str
    model: str
    latency_ms: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    finish_reason: str | None = None

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
    """Minimal native-API Ollama chat client with jittered retries."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout_s: float | None = None,
        max_retries: int | None = None,
        num_ctx: int | None = None,
    ) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.INFERENCE_BASE_URL).rstrip("/")
        self.model = model or settings.INFERENCE_MODEL
        self.timeout_s = timeout_s or settings.INFERENCE_TIMEOUT_S
        self.max_retries = settings.INFERENCE_MAX_RETRIES if max_retries is None else max_retries
        # Defaults to the text path's budget. A vision client passes
        # VISION_NUM_CTX explicitly — an image costs real context, and the two
        # models are not interchangeable here (see config.py). Sent as
        # options.num_ctx below — the native endpoint actually honours it
        # (checked directly: a small num_ctx measurably truncates
        # prompt_eval_count), unlike the OpenAI-compatible endpoint this client
        # used before 2026-09-24.
        self.num_ctx = settings.INFERENCE_NUM_CTX if num_ctx is None else num_ctx

    def chat(
        self, *, system: str, user: str, images: list[bytes] | None = None, json_mode: bool = True
    ) -> ChatResult:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        if images:
            messages[1] = _with_images(user, images)

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "options": {
                # Temperature 0: extraction is not a creative task, and a
                # stable output is what makes a regression measurable.
                "temperature": 0,
                "seed": get_settings().INFERENCE_SEED,
                "num_ctx": self.num_ctx,
            },
            # Explicit, always — never the server's default. A hybrid-reasoning
            # model (qwen3.5) keeps a chain-of-thought running otherwise, which
            # costs real context and, at this model's default temperature 1,
            # measurably changes the answer. See the module docstring.
            "think": False,
            "stream": False,
        }
        if json_mode:
            payload["format"] = "json"

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            started = time.monotonic()
            try:
                with httpx.Client(timeout=self.timeout_s) as client:
                    response = client.post(f"{self.base_url}/api/chat", json=payload)
                    if response.status_code == CLOUDFLARE_TIMEOUT:
                        # Raised inside the try but not caught below: InferenceError is
                        # none of the retried types, so a 524 fails on the first attempt.
                        raise InferenceError(_tunnel_timeout_message(self.base_url))
                    response.raise_for_status()
                    body = response.json()
                message = body["message"]
                result = ChatResult(
                    content=message["content"],
                    model=body.get("model", self.model),
                    latency_ms=int((time.monotonic() - started) * 1000),
                    prompt_tokens=body.get("prompt_eval_count"),
                    completion_tokens=body.get("eval_count"),
                    finish_reason=body.get("done_reason"),
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
            else:
                # Outside the try: a refusal is deterministic, so it is not retried.
                _refuse_if_context_exhausted(result, self.num_ctx)
                return result

        raise InferenceError(
            f"inference failed after {self.max_retries + 1} attempts: {last_error}"
        ) from last_error


def _refuse_if_context_exhausted(result: ChatResult, num_ctx: int) -> None:
    """Ollama truncates an over-long prompt silently and answers anyway.

    The answer then comes from a document with its beginning cut off, which looks
    exactly like a model that missed a field. The only trace is the token count
    sitting at the window, so that is what is checked. Token counts are logged on
    every call so a creeping prompt is visible before it reaches the limit.

    ``num_ctx`` is the CALLING CLIENT's budget (``self.num_ctx``), not a global
    read here — a vision client checks against VISION_NUM_CTX, a text client
    against INFERENCE_NUM_CTX, and they must not be conflated.
    """
    used = (result.prompt_tokens or 0) + (result.completion_tokens or 0)
    logger.info(
        "inference.usage",
        extra={
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "num_ctx": num_ctx,
        },
    )
    if result.finish_reason == "length":
        raise InferenceError(
            "the model stopped at its length limit (finish_reason=length); the reply is incomplete"
        )
    if used >= num_ctx:
        raise InferenceError(
            f"prompt and reply used {used} tokens of a {num_ctx}-token context; the "
            "server truncates silently at that point, so the model may not have seen "
            "the start of the document. Raise the model's context and INFERENCE_NUM_CTX."
        )
    if used >= 0.8 * num_ctx:
        logger.warning("inference.context_nearly_full", extra={"used": used, "num_ctx": num_ctx})


def _with_images(text: str, images: list[bytes]) -> dict[str, Any]:
    """Ollama's native format: base64 strings on an ``images`` field, no
    data-URI wrapper and no OpenAI-style content-parts array."""
    import base64

    return {
        "role": "user",
        "content": text,
        "images": [base64.b64encode(image).decode("ascii") for image in images],
    }
