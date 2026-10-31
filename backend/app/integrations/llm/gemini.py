# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Gemini as the conversation model, behind ``ConversationModelProvider``.

- Structured output: ``application/json`` constrained by the ``TurnProposal`` schema, then
  validated again with Pydantic. Invalid output is an error, never partially applied.
- No tools: function calling is disabled and no tool is declared (ADR-0003).
- Only synthetic demo data exists in this system (reserved contact values are enforced by the
  database), so nothing real can be sent to the provider.
- Google SDK types never leave this module.
"""

import httpx
from google import genai
from google.genai import types
from pydantic import ValidationError

from app.core.logging import get_logger
from app.integrations.llm.base import (
    ProposalResult,
    ProviderError,
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


class GeminiConversationProvider:
    name = PROVIDER
    writes_responses = True

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float,
        http_client: httpx.AsyncClient | None = None,
        base_url: str | None = None,
    ) -> None:
        self._model = model
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=int(timeout_seconds * 1000),
                base_url=base_url,
                httpx_async_client=http_client,
                # Retries are decided by this adapter, not hidden inside the SDK.
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
        response = await self._client.aio.models.generate_content(
            model=self._model, contents=render_turn(context), config=self._config
        )
        proposal = self._parse(response)
        return ProposalResult(proposal=proposal, usage=_usage(response), attempts=1)

    def _parse(self, response: types.GenerateContentResponse) -> TurnProposal:
        text = response.text
        if not text:
            reason = _finish_reason(response)
            raise ProviderError(PROVIDER, f"empty response (finish reason: {reason})")
        try:
            return TurnProposal.model_validate_json(text)
        except ValidationError as error:
            log.warning(
                "llm_invalid_output",
                provider=PROVIDER,
                prompt_version=PROMPT_VERSION,
                errors=error.error_count(),
            )
            raise ProviderError(
                PROVIDER, "response did not match the TurnProposal schema"
            ) from error


def _usage(response: types.GenerateContentResponse) -> TokenUsage | None:
    meta = response.usage_metadata
    if meta is None:
        return None
    return TokenUsage(
        prompt_tokens=meta.prompt_token_count, output_tokens=meta.candidates_token_count
    )


def _finish_reason(response: types.GenerateContentResponse) -> str:
    if response.candidates and response.candidates[0].finish_reason is not None:
        return str(response.candidates[0].finish_reason.value)
    if response.prompt_feedback is not None and response.prompt_feedback.block_reason is not None:
        return f"blocked: {response.prompt_feedback.block_reason.value}"
    return "unknown"
