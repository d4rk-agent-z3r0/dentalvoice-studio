# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Pick the speech providers once, at startup, from ``VOICE_PROVIDER_MODE`` (ADR-0005)."""

from dataclasses import dataclass

from app.core.config import ProviderMode, Settings
from app.integrations.llm.factory import ProviderConfigurationError
from app.integrations.speech.base import SpeechToTextProvider, TextToSpeechProvider
from app.integrations.speech.deepgram_stt import DeepgramSpeechToTextProvider
from app.integrations.speech.deepgram_tts import DeepgramTextToSpeechProvider
from app.integrations.speech.mock import MockSpeechToTextProvider, MockTextToSpeechProvider
from app.voice.clips import ClipLibrary


@dataclass(frozen=True)
class SpeechProviders:
    stt: SpeechToTextProvider
    tts: TextToSpeechProvider


def build_speech_providers(settings: Settings, library: ClipLibrary) -> SpeechProviders:
    if settings.voice_provider_mode is ProviderMode.MOCK:
        return SpeechProviders(MockSpeechToTextProvider(library), MockTextToSpeechProvider())
    missing = [
        name
        for name, value in (
            ("DEEPGRAM_API_KEY", settings.deepgram_api_key),
            ("STT_MODEL", settings.stt_model),
            ("TTS_MODEL", settings.tts_model),
        )
        if value is None
    ]
    if missing:
        raise ProviderConfigurationError(
            f"VOICE_PROVIDER_MODE=live needs {', '.join(missing)}. Set them in your local .env, "
            "or use VOICE_PROVIDER_MODE=mock. The mock is never used as a fallback."
        )
    return SpeechProviders(_deepgram_stt(settings), _deepgram_tts(settings))


def _deepgram_stt(settings: Settings) -> DeepgramSpeechToTextProvider:
    key, model = settings.deepgram_api_key, settings.stt_model
    if key is None or model is None:  # checked above; repeated so the types are narrowed
        raise ProviderConfigurationError("DEEPGRAM_API_KEY and STT_MODEL are required.")
    return DeepgramSpeechToTextProvider(
        api_key=key.get_secret_value(),
        model=model,
        timeout_seconds=settings.speech_timeout_seconds,
    )


def _deepgram_tts(settings: Settings) -> DeepgramTextToSpeechProvider:
    key, model = settings.deepgram_api_key, settings.tts_model
    if key is None or model is None:  # checked above; repeated so the types are narrowed
        raise ProviderConfigurationError("DEEPGRAM_API_KEY and TTS_MODEL are required.")
    return DeepgramTextToSpeechProvider(
        api_key=key.get_secret_value(),
        model=model,
        timeout_seconds=settings.speech_timeout_seconds,
    )
