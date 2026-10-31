# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Gemini as the conversation model, behind ``ConversationModelProvider``.

- Structured output: ``application/json`` constrained by the ``TurnProposal`` schema, then
  validated again with Pydantic. Invalid output is an error, never partially applied.
- No tools: function calling is disabled and no tool is declared (ADR-0003).
- Only synthetic demo data exists in this system (reserved contact values are enforced by the
  database), so nothing real can be sent to the provider.
- Google SDK types never leave this module.

Failure policy for one call to ``propose``:

- Timeout, connection error, HTTP 429 or 5xx: retried with backoff; if every attempt fails,
  ``ProviderUnavailableError`` (HTTP 503 to the client).
- Empty, blocked, truncated or schema-invalid output: re-asked once with the validation errors;
  if still invalid, ``ProviderError`` (502).
- Any other HTTP 4xx (bad request, auth, unknown model): not retried, ``ProviderError`` (502).
"""

import asyncio
import random
from collections.abc import Awaitable, Callable

import httpx
from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from app.core.logging import get_logger
from app.integrations.llm.base import (
    ProposalResult,
    ProviderError,
    ProviderUnavailableError,
    TokenUsage,
    TurnContext,
)
from app.integrations.llm.prompting import (
    PROMPT_VERSION,
    render_turn,
    response_schema,
    system_prompt,
)
from app.schemas.proposal import TurnProposal

log = get_logger(__name__)

PROVIDER = "gemini"
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

Sleep = Callable[[float], Awaitable[None]]


class _InvalidOutputError(Exception):
    def __init__(self, reason: str, raw: str | None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.raw = raw


class _TransientError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class GeminiConversationProvider:
    name = PROVIDER
    writes_responses = True

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float,
        max_attempts: int = 3,
        backoff_seconds: float = 0.5,
        http_client: httpx.AsyncClient | None = None,
        base_url: str | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._model = model
        self._timeout = timeout_seconds
        self._max_attempts = max_attempts
        self._backoff = backoff_seconds
        self._sleep = sleep
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=int(timeout_seconds * 1000),
                base_url=base_url,
                httpx_async_client=http_client,
                # Retries are decided below, not hidden inside the SDK.
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )
        self._config = types.GenerateContentConfig(
            system_instruction=system_prompt(),
            response_mime_type="application/json",
            response_json_schema=response_schema(),
            temperature=0.2,
            candidate_count=1,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            automatic_continuation=False,
        )

    async def propose(self, context: TurnContext) -> ProposalResult:
        contents: list[types.Content] = [
            types.Content(role="user", parts=[types.Part(text=render_turn(context))])
        ]
        prompt_tokens = output_tokens = 0
        reported = False
        reasked = False
        last_failure = "no attempt made"

        for attempt in range(1, self._max_attempts + 1):
            try:
                response = await self._call(contents)
            except _TransientError as error:
                last_failure = error.reason
                self._log_retry(attempt, "transient", error.reason)
                if attempt < self._max_attempts:
                    await self._sleep(self._delay(attempt))
                continue

            usage = _usage(response)
            if usage is not None:
                reported = True
                prompt_tokens += usage.prompt_tokens or 0
                output_tokens += usage.output_tokens or 0
            try:
                proposal = _parse(response)
            except _InvalidOutputError as error:
                self._log_retry(attempt, "invalid_output", error.reason)
                if reasked or attempt == self._max_attempts:
                    raise ProviderError(
                        PROVIDER, f"invalid structured output: {error.reason}"
                    ) from error
                # One corrective re-ask: show the model its output and why it was rejected.
                reasked = True
                contents = [*contents, *_correction(error)]
                continue

            totals = TokenUsage(prompt_tokens, output_tokens) if reported else None
            return ProposalResult(proposal=proposal, usage=totals, attempts=attempt)

        raise ProviderUnavailableError(
            PROVIDER, f"no usable response after {self._max_attempts} attempts ({last_failure})"
        )

    async def _call(self, contents: list[types.Content]) -> types.GenerateContentResponse:
        try:
            async with asyncio.timeout(self._timeout):
                return await self._client.aio.models.generate_content(
                    model=self._model, contents=contents, config=self._config
                )
        except TimeoutError as error:
            raise _TransientError(f"timed out after {self._timeout:g}s") from error
        except httpx.TransportError as error:
            raise _TransientError(type(error).__name__) from error
        except errors.APIError as error:
            if error.code in _RETRYABLE_STATUS:
                raise _TransientError(f"HTTP {error.code} {error.status or ''}".strip()) from error
            # Not retryable: the request itself, the key or the model id is wrong.
            raise ProviderError(
                PROVIDER, f"HTTP {error.code} {error.status or ''}".strip()
            ) from error

    def _delay(self, attempt: int) -> float:
        base = self._backoff * 2 ** (attempt - 1)
        return float(base + random.uniform(0, base / 2))  # noqa: S311 - jitter, not security

    @staticmethod
    def _log_retry(attempt: int, kind: str, reason: str) -> None:
        log.warning(
            "llm_attempt_failed",
            provider=PROVIDER,
            prompt_version=PROMPT_VERSION,
            attempt=attempt,
            kind=kind,
            reason=reason,
        )


def _parse(response: types.GenerateContentResponse) -> TurnProposal:
    raw = response.text
    if not raw:
        raise _InvalidOutputError(f"empty response ({_finish_reason(response)})", None)
    candidate = response.candidates[0] if response.candidates else None
    if candidate is not None and candidate.finish_reason == types.FinishReason.MAX_TOKENS:
        raise _InvalidOutputError("output truncated (MAX_TOKENS)", raw)
    try:
        return TurnProposal.model_validate_json(raw)
    except ValidationError as error:
        # Locations and error types only: the raw output may contain caller data.
        summary = "; ".join(
            f"{'.'.join(str(p) for p in item['loc']) or '(root)'}: {item['type']}"
            for item in error.errors()[:5]
        )
        raise _InvalidOutputError(f"schema mismatch: {summary}", raw) from error


def _correction(error: _InvalidOutputError) -> list[types.Content]:
    turns = []
    if error.raw:
        turns.append(types.Content(role="model", parts=[types.Part(text=error.raw[:4000])]))
    turns.append(
        types.Content(
            role="user",
            parts=[
                types.Part(
                    text=(
                        "Your previous reply could not be used: "
                        f"{error.reason}. Reply again with exactly one JSON object that matches "
                        "the response schema, using only the allowed field names and enum values."
                    )
                )
            ],
        )
    )
    return turns


def _usage(response: types.GenerateContentResponse) -> TokenUsage | None:
    meta = response.usage_metadata
    if meta is None:
        return None
    return TokenUsage(
        prompt_tokens=meta.prompt_token_count, output_tokens=meta.candidates_token_count
    )


def _finish_reason(response: types.GenerateContentResponse) -> str:
    if response.prompt_feedback is not None and response.prompt_feedback.block_reason is not None:
        return f"blocked: {response.prompt_feedback.block_reason.value}"
    if response.candidates and response.candidates[0].finish_reason is not None:
        return f"finish reason: {response.candidates[0].finish_reason.value}"
    return "no candidates"
