# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Failure handling of the Gemini adapter, through the real SDK with the network replaced."""

import json
from typing import Any

import httpx
import pytest

from app.integrations.llm.base import ProviderError, ProviderUnavailableError
from app.integrations.llm.gemini import GeminiConversationProvider
from tests.contract.gemini_fake import FakeGemini, context, payload


class RecordingSleep:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def provider(
    fake: FakeGemini, **overrides: Any
) -> tuple[GeminiConversationProvider, RecordingSleep]:
    sleep = RecordingSleep()
    return fake.provider(sleep=sleep, **overrides), sleep


@pytest.mark.parametrize(
    "transient",
    [
        (503, "error_503.json"),
        (500, "error_500.json"),
        (429, "error_429.json"),
        httpx.ConnectError("connection refused"),
        httpx.ReadTimeout("read timed out"),
    ],
    ids=["503", "500", "429", "connect-error", "read-timeout"],
)
async def test_transient_failures_are_retried(transient: Any) -> None:
    fake = FakeGemini(transient, (200, "ok_introduction.json"))
    gemini, sleep = provider(fake)

    result = await gemini.propose(context())

    assert result.attempts == 2
    assert len(sleep.delays) == 1
    assert fake.remaining == 0


async def test_persistent_outage_becomes_provider_unavailable_after_the_attempt_budget() -> None:
    fake = FakeGemini(*[(503, "error_503.json")] * 3)
    gemini, sleep = provider(fake, max_attempts=3, backoff_seconds=0.5)

    with pytest.raises(ProviderUnavailableError, match="3 attempts") as caught:
        await gemini.propose(context())

    assert caught.value.code == "PROVIDER_UNAVAILABLE"
    assert len(fake.requests) == 3
    assert len(sleep.delays) == 2  # no sleep after the final attempt
    assert 0.5 <= sleep.delays[0] <= 0.75
    assert 1.0 <= sleep.delays[1] <= 1.5  # exponential backoff with bounded jitter


@pytest.mark.parametrize(("status", "fixture"), [(400, "error_400.json"), (403, "error_403.json")])
async def test_client_errors_are_not_retried(status: int, fixture: str) -> None:
    fake = FakeGemini((status, fixture))
    gemini, sleep = provider(fake)

    with pytest.raises(ProviderError) as caught:
        await gemini.propose(context())

    assert not isinstance(caught.value, ProviderUnavailableError)
    assert str(status) in caught.value.message
    assert len(fake.requests) == 1
    assert sleep.delays == []


async def test_a_slow_provider_is_cut_off_by_the_timeout_and_retried() -> None:
    fake = FakeGemini(1.0, (200, "ok_introduction.json"), (200, "ok_introduction.json"))
    gemini, _ = provider(fake, timeout_seconds=0.05)

    result = await gemini.propose(context())

    assert result.attempts == 2


async def test_invalid_output_is_re_asked_once_with_the_reasons_and_no_values() -> None:
    fake = FakeGemini((200, "schema_violation.json"), (200, "ok_introduction.json"))
    gemini, sleep = provider(fake)

    result = await gemini.propose(context())

    assert result.attempts == 2
    assert sleep.delays == []  # a re-ask is not a backoff
    second = fake.requests[1]["contents"]
    assert [turn["role"] for turn in second] == ["user", "model", "user"]
    correction = second[2]["parts"][0]["text"]
    assert "next_action" in correction  # where the problem was
    assert "BOOK_APPOINTMENT" not in correction  # never the offending value itself
    # Usage is summed over both calls.
    assert result.usage is not None
    assert result.usage.prompt_tokens == 812 * 2


async def test_output_invalid_twice_is_an_error_not_a_guess() -> None:
    fake = FakeGemini((200, "invalid_json.json"), (200, "schema_violation.json"))
    gemini, _ = provider(fake, max_attempts=5)

    with pytest.raises(ProviderError, match="invalid structured output"):
        await gemini.propose(context())

    assert len(fake.requests) == 2  # only one re-ask, whatever the attempt budget


def test_fixtures_parse_with_the_sdks_own_response_type() -> None:
    from google.genai import types

    for name in ("ok_introduction.json", "safety_blocked.json", "max_tokens_truncated.json"):
        parsed = types.GenerateContentResponse.model_validate(payload(name))
        assert parsed is not None
    ok = types.GenerateContentResponse.model_validate(payload("ok_introduction.json"))
    assert json.loads(ok.text or "")["next_action"] == "ASK_NEXT_FIELD"
