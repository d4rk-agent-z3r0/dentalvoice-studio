# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Pick the conversation model once, at startup, from ``VOICE_PROVIDER_MODE`` (ADR-0005)."""

from app.core.config import ProviderMode, Settings
from app.integrations.llm.base import ConversationModelProvider
from app.integrations.llm.mock import MockConversationProvider


class ProviderConfigurationError(RuntimeError):
    """Raised at startup; the application refuses to run with a half-configured live mode."""


def build_conversation_provider(settings: Settings) -> ConversationModelProvider:
    if settings.voice_provider_mode is ProviderMode.MOCK:
        return MockConversationProvider()
    raise ProviderConfigurationError(
        "VOICE_PROVIDER_MODE=live requires the Gemini provider, which is added in Milestone 4. "
        "Use VOICE_PROVIDER_MODE=mock until then."
    )
