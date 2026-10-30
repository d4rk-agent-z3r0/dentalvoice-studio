from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import REPO_ROOT_ENV_FILE, ProviderMode, Settings


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


def test_unknown_log_level_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")
    monkeypatch.setenv("LOG_LEVEL", "verbose")
    with pytest.raises(ValidationError, match="log_level"):
        Settings(_env_file=None)


def test_default_env_file_is_the_repository_root() -> None:
    assert REPO_ROOT_ENV_FILE.name == ".env"
    assert (REPO_ROOT_ENV_FILE.parent / "backend" / "app" / "core" / "config.py").is_file()


def test_env_file_values_are_read_verbatim(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    env_file = tmp_path / ".env"
    # '#' and '$' are legal in a password and must survive (Make-style parsing would mangle them).
    env_file.write_text("DATABASE_URL=postgresql+asyncpg://u:pa%23ss$x@localhost:5432/db\n")
    settings = Settings(_env_file=env_file)
    assert settings.database_url.hosts()[0]["password"] == "pa%23ss$x"


def test_environment_variables_override_env_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("DATABASE_URL=postgresql+asyncpg://u:p@from-file:5432/db\n")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@from-env:5432/db")
    settings = Settings(_env_file=env_file)
    assert settings.database_url.hosts()[0]["host"] == "from-env"
