# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
import pytest
from pydantic import SecretStr

from app.core.config import ProviderMode
from app.integrations.llm.factory import ProviderConfigurationError
from app.integrations.speech.deepgram_stt import DeepgramSpeechToTextProvider
from app.integrations.speech.factory import _deepgram_stt, build_speech_providers
from app.integrations.speech.mock import MockSpeechToTextProvider, MockTextToSpeechProvider
from app.voice.clips import default_library
from tests.conftest import UNREACHABLE_DATABASE_URL, make_test_settings


def test_mock_mode_uses_the_speech_mocks_without_credentials() -> None:
    providers = build_speech_providers(
        make_test_settings(UNREACHABLE_DATABASE_URL), default_library()
    )
    assert isinstance(providers.stt, MockSpeechToTextProvider)
    assert isinstance(providers.tts, MockTextToSpeechProvider)


@pytest.mark.parametrize(
    ("overrides", "missing"),
    [
        ({}, "DEEPGRAM_API_KEY, STT_MODEL, TTS_MODEL"),
        ({"deepgram_api_key": SecretStr("k" * 20), "stt_model": "stt-test"}, "TTS_MODEL"),
    ],
)
def test_live_speech_without_credentials_refuses_to_start(
    overrides: dict[str, object], missing: str
) -> None:
    settings = make_test_settings(
        UNREACHABLE_DATABASE_URL, voice_provider_mode=ProviderMode.LIVE, **overrides
    )
    with pytest.raises(ProviderConfigurationError, match=missing):
        build_speech_providers(settings, default_library())


def test_live_mode_with_every_setting_builds_deepgram_stt_without_network() -> None:
    settings = make_test_settings(
        UNREACHABLE_DATABASE_URL,
        voice_provider_mode=ProviderMode.LIVE,
        deepgram_api_key=SecretStr("k" * 20),
        stt_model="stt-test",
        tts_model="tts-test",
    )
    stt = _deepgram_stt(settings)  # constructing opens no connection
    assert isinstance(stt, DeepgramSpeechToTextProvider)
    assert "model=stt-test" in stt.stream_url(sample_rate=16_000)
    assert "k" * 20 not in stt.stream_url(sample_rate=16_000)
    with pytest.raises(ProviderConfigurationError, match="text-to-speech is not wired yet"):
        build_speech_providers(settings, default_library())
