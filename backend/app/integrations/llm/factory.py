# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Pick the conversation model once, at startup, from ``VOICE_PROVIDER_MODE`` (ADR-0005)."""

from app.core.config import ProviderMode, Settings
from app.integrations.llm.base import ConversationModelProvider
from app.integrations.llm.gemini import GeminiConversationProvider
from app.integrations.llm.mock import MockConversationProvider


class ProviderConfigurationError(RuntimeError):
    """Raised at startup; the application refuses to run with a half-configured live mode."""


def build_conversation_provider(settings: Settings) -> ConversationModelProvider:
    if settings.voice_provider_mode is ProviderMode.MOCK:
        return MockConversationProvider()
    missing = [
        name
        for name, value in (
            ("GEMINI_API_KEY", settings.gemini_api_key),
            ("GEMINI_MODEL", settings.gemini_model),
        )
        if value is None
    ]
    if missing or settings.gemini_api_key is None or settings.gemini_model is None:
        raise ProviderConfigurationError(
            f"VOICE_PROVIDER_MODE=live needs {', '.join(missing)}. Set them in your local .env, "
            "or use VOICE_PROVIDER_MODE=mock. The mock is never used as a fallback."
        )
    return GeminiConversationProvider(
        api_key=settings.gemini_api_key.get_secret_value(),
        model=settings.gemini_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )
