# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Errors shared by every external provider (conversation model, speech-to-text, text-to-speech)."""


class ProviderError(Exception):
    """A provider call failed. Surfaced to the user; never replaced by a mock (ADR-0005)."""

    code = "PROVIDER_ERROR"

    def __init__(self, provider: str, message: str) -> None:
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.message = message


class ProviderUnavailableError(ProviderError):
    """Transient: timeouts, rate limits and server errors that persisted through retries."""

    code = "PROVIDER_UNAVAILABLE"
