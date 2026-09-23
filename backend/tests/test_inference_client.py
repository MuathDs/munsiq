"""The inference client's guarantees, tested against a fake endpoint.

Found while diagnosing a run of missed fields on a real invoice. The context was
NOT the cause (1,142 tokens against 4,096, nothing truncated), but the client
could not have told: it discarded ``usage``, sent no seed, and would have passed a
silently truncated prompt straight through.
"""

from __future__ import annotations

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
    finish_reason: str = "stop",
) -> list[dict[str, Any]]:
    """Route the client at a canned response. Returns the payloads it received."""
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "qwen2.5:7b-instruct",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": '{"a": 1}'},
                        "finish_reason": finish_reason,
                    }
                ],
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                },
            },
        )

    real_client = httpx.Client

    def make_client(*args: Any, **kwargs: Any) -> httpx.Client:
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", make_client)
    return seen


def test_temperature_is_zero_and_a_seed_is_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = fake_endpoint(monkeypatch)

    OllamaClient(max_retries=0).chat(system="s", user="u")

    assert seen[0]["temperature"] == 0
    assert seen[0]["seed"] == get_settings().INFERENCE_SEED


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
    fake_endpoint(monkeypatch, finish_reason="length")

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
