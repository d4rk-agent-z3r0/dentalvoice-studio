# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Application settings, loaded once from the environment."""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, PostgresDsn, SecretStr, field_validator
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
    # HS256 signing key for access tokens. No default: tokens cannot be issued or verified without
    # it, and a weak key is rejected at startup.
    jwt_secret: SecretStr | None = None
    jwt_ttl_minutes: int = Field(default=60, ge=1, le=24 * 60)
    booking_horizon_days: int = Field(default=60, ge=1, le=365)

    @field_validator("jwt_secret")
    @classmethod
    def _strong_secret(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and len(value.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters.")
        return value

    @property
    def text_turns_enabled(self) -> bool:
        """The typed-turn endpoint exists for development and tests only."""
        return self.environment is not Environment.PRODUCTION


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
