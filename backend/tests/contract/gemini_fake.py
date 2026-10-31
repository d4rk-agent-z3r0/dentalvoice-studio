# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""A scripted stand-in for the Gemini HTTP API, plugged into the real SDK via httpx.

The adapter and ``google-genai`` run unmodified; only the network is replaced.
"""

import asyncio
import json
from collections import deque
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from app.domain.enums import ConversationState
from app.integrations.llm.base import TurnContext
from app.integrations.llm.gemini import GeminiConversationProvider

PAYLOADS = Path(__file__).parent / "payloads" / "gemini"


def payload(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((PAYLOADS / name).read_text())
    return data


Scripted = tuple[int, str | dict[str, Any]] | Exception | float


def proposal_response(
    proposal: dict[str, Any], usage: tuple[int, int] = (700, 60)
) -> dict[str, Any]:
    """A documented-shape ``generateContent`` response whose text is ``proposal`` as JSON."""
    return {
        "candidates": [
            {
                "content": {"parts": [{"text": json.dumps(proposal)}], "role": "model"},
                "finishReason": "STOP",
                "index": 0,
            }
        ],
        "usageMetadata": {
            "promptTokenCount": usage[0],
            "candidatesTokenCount": usage[1],
            "totalTokenCount": sum(usage),
        },
        "modelVersion": "gemini-test-model",
    }


class FakeGemini:
    def __init__(self, *responses: Scripted) -> None:
        """Each item: ``(status, payload file name or dict)``, an exception raised by the
        transport, or a float: seconds to stall before answering with the next item."""
        self._queue: deque[Scripted] = deque(responses)
        self.requests: list[dict[str, Any]] = []
        self.urls: list[str] = []
        self.headers: list[dict[str, str]] = []

    async def _handle(self, request: httpx.Request) -> httpx.Response:
        self.urls.append(str(request.url))
        self.headers.append(dict(request.headers))
        self.requests.append(json.loads(request.content))
        if not self._queue:
            raise AssertionError("FakeGemini received more requests than scripted")
        item = self._queue.popleft()
        if isinstance(item, float):
            await asyncio.sleep(item)
            item = self._queue.popleft()
        if isinstance(item, Exception):
            raise item
        if isinstance(item, float):
            raise AssertionError("two stalls in a row")
        status, body = item
        return httpx.Response(status, json=payload(body) if isinstance(body, str) else body)

    def provider(self, **overrides: Any) -> GeminiConversationProvider:
        options: dict[str, Any] = {
            "api_key": "test-key-not-real",
            "model": "gemini-test-model",
            "timeout_seconds": 5.0,
            "http_client": httpx.AsyncClient(transport=httpx.MockTransport(self._handle)),
            **overrides,
        }
        return GeminiConversationProvider(**options)

    @property
    def remaining(self) -> int:
        return len(self._queue)


def context(utterance: str = "Hi, I'm a new patient and I'd like a cleaning.") -> TurnContext:
    return TurnContext(
        clinic_name="BrightSmile Dental Studio",
        clinic_today=date(2026, 11, 2),
        state=ConversationState.GREETING,
        utterance=utterance,
        known_values={},
        missing_fields=[],
        services={"hygiene_cleaning": "Hygiene cleaning", "checkup": "Routine check-up"},
        history=[],
    )
