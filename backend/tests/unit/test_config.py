import pytest
from pydantic import ValidationError

from app.core.config import ProviderMode, Settings


def test_database_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError, match="database_url"):
        Settings(_env_file=None)


def test_provider_mode_defaults_to_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VOICE_PROVIDER_MODE", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")
    settings = Settings(_env_file=None)
    assert settings.voice_provider_mode is ProviderMode.MOCK


def test_unknown_provider_mode_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")
    monkeypatch.setenv("VOICE_PROVIDER_MODE", "maybe")
    with pytest.raises(ValidationError, match="voice_provider_mode"):
        Settings(_env_file=None)
