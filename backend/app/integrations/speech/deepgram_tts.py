# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Deepgram Aura text-to-speech over streaming HTTP, behind ``TextToSpeechProvider``.

``POST https://api.deepgram.com/v1/speak?model=...&encoding=linear16&sample_rate=24000&container=none``
with the JSON body ``{"text": ...}``. With ``container=none`` the response body is raw 16-bit
little-endian PCM with no WAV header, and Deepgram documents that playback may begin as soon as the
first bytes arrive. Chunks are yielded as they are received, trimmed so each one holds whole
samples (a network read can split a sample in two; the odd byte is carried to the next chunk).

Failure policy for one call to ``synthesize``:

- HTTP 4xx other than 429 (bad request, invalid key, no credits, text too long): ``ProviderError``
  (502), never retried.
- HTTP 429 or 5xx, a connection error or a timeout before any audio was yielded: retried once
  after a short pause; if that fails too, ``ProviderUnavailableError`` (503).
- Any failure after the first audio chunk was yielded: ``ProviderUnavailableError`` at once. The
  caller has already played part of the reply, so a retry would repeat it; no silence or mock audio
  is substituted (ADR-0005).
- No audio at all in a successful response: ``ProviderError``.

``timeout_seconds`` bounds the wait for the response headers and for each chunk of the body. The
API key travels only in the ``Authorization`` header; reply text and audio are never logged.
httpx types never leave this module.
"""

import asyncio
import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import aclosing

import httpx

from app.core.logging import get_logger
from app.integrations.errors import ProviderError, ProviderUnavailableError
from app.integrations.speech.base import AudioFormat

log = get_logger(__name__)

PROVIDER = "deepgram-tts"
DEFAULT_BASE_URL = "https://api.deepgram.com"
_SPEAK_PATH = "/v1/speak"
_MAX_ATTEMPTS = 2  # at most one retry, and only before any audio was yielded

Sleep = Callable[[float], Awaitable[None]]


class _TransientError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class DeepgramTextToSpeechProvider:
    name = PROVIDER
    output_format = AudioFormat(sample_rate=24_000)

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float,
        base_url: str = DEFAULT_BASE_URL,
        http_client: httpx.AsyncClient | None = None,
        retry_delay_seconds: float = 0.25,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_seconds
        self._url = base_url.rstrip("/") + _SPEAK_PATH
        self._client = http_client or httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds))
        self._retry_delay = retry_delay_seconds
        self._sleep = sleep
        self._sample_bytes = 2 * self.output_format.channels  # linear16: two bytes per sample

    async def synthesize(self, text: str) -> AsyncGenerator[bytes]:
        last_failure = "no attempt made"
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            yielded = False
            try:
                # ``aclosing``: the HTTP response is released as soon as the consumer stops or
                # is cancelled, not when the generator is garbage collected.
                async with aclosing(self._stream(text)) as chunks:
                    async for chunk in chunks:
                        yielded = True
                        yield chunk
                return
            except _TransientError as error:
                last_failure = error.reason
                log.warning(
                    "tts_attempt_failed",
                    provider=PROVIDER,
                    attempt=attempt,
                    reason=error.reason,
                    after_audio=yielded,
                )
                if yielded:
                    raise ProviderUnavailableError(
                        PROVIDER, f"audio stream interrupted ({error.reason})"
                    ) from error
                if attempt < _MAX_ATTEMPTS:
                    await self._sleep(self._retry_delay)
        raise ProviderUnavailableError(
            PROVIDER, f"no audio after {_MAX_ATTEMPTS} attempts ({last_failure})"
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _stream(self, text: str) -> AsyncGenerator[bytes]:
        request = self._client.build_request(
            "POST",
            self._url,
            params={
                "model": self._model,
                "encoding": self.output_format.encoding,
                "sample_rate": str(self.output_format.sample_rate),
                "container": "none",
            },
            headers={"Authorization": f"Token {self._api_key}", "Accept": "audio/*"},
            json={"text": text},
        )
        try:
            async with asyncio.timeout(self._timeout):
                response = await self._client.send(request, stream=True)
        except TimeoutError as error:
            raise _TransientError(f"no response within {self._timeout:g}s") from error
        except httpx.TimeoutException as error:
            raise _TransientError(type(error).__name__) from error
        except httpx.TransportError as error:
            raise _TransientError(type(error).__name__) from error

        try:
            if response.status_code >= 400:
                await self._raise_for_status(response)
            carry = b""
            received = 0
            body = response.aiter_bytes()
            while True:
                try:
                    async with asyncio.timeout(self._timeout):
                        chunk = await anext(body)
                except StopAsyncIteration:
                    break
                except TimeoutError as error:
                    raise _TransientError(f"no audio data within {self._timeout:g}s") from error
                except (httpx.TimeoutException, httpx.TransportError) as error:
                    raise _TransientError(type(error).__name__) from error
                received += len(chunk)
                data = carry + chunk
                whole = len(data) - len(data) % self._sample_bytes
                carry = data[whole:]
                if whole:
                    yield data[:whole]
            if received == 0:
                raise ProviderError(PROVIDER, "response contained no audio")
            if carry:
                log.warning("tts_partial_sample_dropped", provider=PROVIDER, bytes=len(carry))
        finally:
            await response.aclose()

    @staticmethod
    async def _raise_for_status(response: httpx.Response) -> None:
        status = response.status_code
        try:
            body = json.loads(await response.aread())
        except (ValueError, httpx.HTTPError):
            body = None
        code = None
        if isinstance(body, dict):
            # Deepgram documents ``err_code``; its 503 example uses ``error_code``.
            code = body.get("err_code") or body.get("error_code")
        reason = f"HTTP {status}" + (f" {str(code)[:80]}" if code else "")
        if status == 429 or status >= 500:
            raise _TransientError(reason)
        raise ProviderError(PROVIDER, reason)
