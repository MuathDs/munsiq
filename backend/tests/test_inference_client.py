"""The inference client's guarantees, tested against a fake endpoint.

Found while diagnosing a run of missed fields on a real invoice. The context was
NOT the cause (1,142 tokens against 4,096, nothing truncated), but the client
could not have told: it discarded ``usage``, sent no seed, and would have passed a
silently truncated prompt straight through.

Switched from the OpenAI-compatible ``/v1/chat/completions`` to Ollama's native
``/api/chat`` on 2026-09-24: checked directly, the OpenAI-compatible endpoint
silently ignores ``think``, so a hybrid-reasoning model (qwen3.5) kept a
chain-of-thought running no matter what was sent. This file's fake endpoint
therefore speaks the native response shape (``message``, ``prompt_eval_count``,
``eval_count``, ``done_reason``), and every request-shape assertion reads
``options`` for the sampling parameters.
"""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx
import pytest

from app.config import get_settings
from app.services.extraction.client import InferenceError, OllamaClient


def fake_endpoint(
    monkeypatch: pytest.MonkeyPatch,
    *,
    prompt_tokens: int = 1142,
    completion_tokens: int = 166,
    done_reason: str = "stop",
) -> list[dict[str, Any]]:
    """Route the client at a canned response. Returns the payloads it received."""
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "qwen2.5:7b-instruct",
                "message": {"role": "assistant", "content": '{"a": 1}'},
                "done_reason": done_reason,
                "prompt_eval_count": prompt_tokens,
                "eval_count": completion_tokens,
            },
        )

    real_client = httpx.Client

    def make_client(*args: Any, **kwargs: Any) -> httpx.Client:
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", make_client)
    return seen


# --------------------------------------------------------------------------- #
# Explicit, every call — never a server default
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("json_mode", [True, False])
@pytest.mark.parametrize("with_images", [True, False])
def test_temperature_seed_think_and_num_ctx_are_always_explicit(
    monkeypatch: pytest.MonkeyPatch, json_mode: bool, with_images: bool
) -> None:
    """Ollama's own defaults are unsafe to rely on: qwen3.5 defaults to
    temperature 1, and the OpenAI-compatible endpoint silently ignored `think`
    altogether. Every request, whatever its shape, must carry all four."""
    seen = fake_endpoint(monkeypatch)
    images = [b"fake-webp-bytes"] if with_images else None

    OllamaClient(max_retries=0).chat(system="s", user="u", images=images, json_mode=json_mode)

    request = seen[0]
    assert request["options"]["temperature"] == 0
    assert request["options"]["seed"] == get_settings().INFERENCE_SEED
    assert request["options"]["num_ctx"] == get_settings().INFERENCE_NUM_CTX
    assert request["think"] is False


def test_the_endpoint_is_ollamas_native_api_not_the_openai_compatible_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A regression to /v1/chat/completions would silently un-fix the `think`
    bug this switch exists for — assert the request shape directly, not just
    that a response gets parsed."""
    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(
            200,
            json={
                "model": "qwen2.5:7b-instruct",
                "message": {"role": "assistant", "content": "{}"},
                "done_reason": "stop",
                "prompt_eval_count": 10,
                "eval_count": 5,
            },
        )

    real_client = httpx.Client

    def make_client(*args: Any, **kwargs: Any) -> httpx.Client:
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", make_client)

    OllamaClient(max_retries=0, base_url="http://localhost:11434").chat(system="s", user="u")

    assert requested_urls == ["http://localhost:11434/api/chat"]


def test_images_use_ollamas_native_shape_not_openai_content_parts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = fake_endpoint(monkeypatch)

    OllamaClient(max_retries=0).chat(system="s", user="u", images=[b"one", b"two"])

    user_message = seen[0]["messages"][1]
    assert user_message["content"] == "u"
    assert user_message["images"] == [
        base64.b64encode(b"one").decode("ascii"),
        base64.b64encode(b"two").decode("ascii"),
    ]


def test_json_mode_uses_native_format_field(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = fake_endpoint(monkeypatch)

    OllamaClient(max_retries=0).chat(system="s", user="u", json_mode=True)
    assert seen[0]["format"] == "json"

    OllamaClient(max_retries=0).chat(system="s", user="u", json_mode=False)
    assert "format" not in seen[1]


# --------------------------------------------------------------------------- #
# Token usage and context-overflow guard
# --------------------------------------------------------------------------- #
def test_token_usage_is_captured(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_endpoint(monkeypatch, prompt_tokens=1142, completion_tokens=166)

    result = OllamaClient(max_retries=0).chat(system="s", user="u")

    assert (result.prompt_tokens, result.completion_tokens) == (1142, 166)
    assert result.finish_reason == "stop"


def test_a_prompt_that_fills_the_window_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ollama truncates silently and keeps answering, so the only sign is the
    token count sitting at the limit."""
    num_ctx = get_settings().INFERENCE_NUM_CTX
    fake_endpoint(monkeypatch, prompt_tokens=num_ctx - 10, completion_tokens=40)

    with pytest.raises(InferenceError, match="context"):
        OllamaClient(max_retries=0).chat(system="s", user="u")


def test_a_reply_cut_off_by_the_length_limit_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_endpoint(monkeypatch, done_reason="length")

    with pytest.raises(InferenceError, match="length"):
        OllamaClient(max_retries=0).chat(system="s", user="u")


def test_a_prompt_well_inside_the_window_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_endpoint(monkeypatch, prompt_tokens=1460, completion_tokens=187)

    assert OllamaClient(max_retries=0).chat(system="s", user="u").content == '{"a": 1}'


def test_num_ctx_override_is_checked_instead_of_the_text_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A vision client passes its own (smaller or larger) budget explicitly.

    Here it is smaller than INFERENCE_NUM_CTX, and the usage sits between the
    two: under the text budget, over the client's own — so this only fails
    loudly if the override is actually what gets checked.
    """
    text_num_ctx = get_settings().INFERENCE_NUM_CTX
    override = text_num_ctx - 100
    assert override > 0
    fake_endpoint(monkeypatch, prompt_tokens=override, completion_tokens=10)

    with pytest.raises(InferenceError, match="context"):
        OllamaClient(max_retries=0, num_ctx=override).chat(system="s", user="u")


def test_num_ctx_override_is_sent_as_the_request_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """Not just checked after the fact — actually requested, since the native
    endpoint (unlike the OpenAI-compatible one) honours options.num_ctx."""
    seen = fake_endpoint(monkeypatch)
    override = get_settings().INFERENCE_NUM_CTX - 100

    OllamaClient(max_retries=0, num_ctx=override).chat(system="s", user="u")

    assert seen[0]["options"]["num_ctx"] == override


def test_num_ctx_override_defaults_to_the_text_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_endpoint(monkeypatch, prompt_tokens=1142, completion_tokens=166)

    assert OllamaClient(max_retries=0).num_ctx == get_settings().INFERENCE_NUM_CTX


def test_the_guard_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """The same prompt would overflow again; retrying only burns GPU time."""
    num_ctx = get_settings().INFERENCE_NUM_CTX
    seen = fake_endpoint(monkeypatch, prompt_tokens=num_ctx, completion_tokens=1)

    with pytest.raises(InferenceError):
        OllamaClient(max_retries=2).chat(system="s", user="u")

    assert len(seen) == 1
