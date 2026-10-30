"""Application settings, loaded once from the environment."""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository-root .env (backend/app/core/config.py -> repo root). Absent inside containers, where
# configuration comes from real environment variables. Environment variables always win.
REPO_ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class ProviderMode(StrEnum):
    MOCK = "mock"
    LIVE = "live"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT_ENV_FILE, extra="ignore", frozen=True)

    environment: Environment = Environment.DEVELOPMENT
    # Required: no default so credentials never live in source.
    database_url: PostgresDsn
    voice_provider_mode: ProviderMode = ProviderMode.MOCK
    log_level: LogLevel = "INFO"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_connect_timeout_seconds: float = Field(default=3.0, gt=0)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
