# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""A scripted stand-in for the Gemini HTTP API, plugged into the real SDK via httpx.

The adapter and ``google-genai`` run unmodified; only the network is replaced.
"""

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


class FakeGemini:
    def __init__(self, *responses: tuple[int, str] | Exception) -> None:
        """Each response is ``(status, payload file)`` or an exception raised by the transport."""
        self._queue: deque[tuple[int, str] | Exception] = deque(responses)
        self.requests: list[dict[str, Any]] = []
        self.urls: list[str] = []
        self.headers: list[dict[str, str]] = []

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.urls.append(str(request.url))
        self.headers.append(dict(request.headers))
        self.requests.append(json.loads(request.content))
        if not self._queue:
            raise AssertionError("FakeGemini received more requests than scripted")
        item = self._queue.popleft()
        if isinstance(item, Exception):
            raise item
        status, name = item
        return httpx.Response(status, json=payload(name))

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
