# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Application settings, loaded once from the environment."""

import re
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, PostgresDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.passwords import validate_new_password

# Repository-root .env (backend/app/core/config.py -> repo root). Absent inside containers, where
# configuration comes from real environment variables. Environment variables always win.
REPO_ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


_ORIGIN = re.compile(r"https?://[a-z0-9.\-]+(:[0-9]{1,5})?")


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
    # Password for the seeded demo users (`make seed`). Local .env only, never committed. Unset
    # means the demo users get no password and cannot sign in with one.
    demo_password: SecretStr | None = None
    # Rate limits (token buckets, per process; docs/api-reference.md "Rate limits").
    rate_limits_enabled: bool = True
    rate_login_per_ip_per_minute: int = Field(default=20, ge=1, le=10_000)
    rate_login_failures_per_account: int = Field(default=5, ge=1, le=1_000)  # per 15 minutes
    rate_requests_per_user_per_minute: int = Field(default=600, ge=1, le=100_000)
    rate_writes_per_user_per_minute: int = Field(default=120, ge=1, le=100_000)
    booking_horizon_days: int = Field(default=60, ge=1, le=365)
    # Live conversation model (VOICE_PROVIDER_MODE=live). Model ids change over time, so there is
    # no default: the operator names the model explicitly (see docs/providers.md).
    gemini_api_key: SecretStr | None = None
    gemini_model: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9.\-]{2,63}$")
    llm_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    llm_max_attempts: int = Field(default=3, ge=1, le=5)
    # Live speech (VOICE_PROVIDER_MODE=live): Deepgram. No default model ids
    # (see docs/providers.md).
    deepgram_api_key: SecretStr | None = None
    stt_model: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9.\-]{1,63}$")
    tts_model: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9.\-]{1,63}$")
    speech_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    # 1.0 streams caller fixtures to STT in real time (a live call); 0 streams as fast as possible
    # (tests). Latency figures are only meaningful at 1.0.
    voice_realtime_factor: float = Field(default=1.0, ge=0, le=4)

    @field_validator(
        "jwt_secret",
        "demo_password",
        "gemini_api_key",
        "gemini_model",
        "deepgram_api_key",
        "stt_model",
        "tts_model",
        mode="before",
    )
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        """``KEY=`` in .env (as in .env.example) means "not set", not an empty value."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("jwt_secret")
    @classmethod
    def _strong_secret(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and len(value.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters.")
        return value

    @field_validator("cors_origins")
    @classmethod
    def _exact_origins(cls, value: list[str]) -> list[str]:
        """Browser origins allowed to call the API and open its WebSocket: exact values only."""
        for origin in value:
            if not _ORIGIN.fullmatch(origin):
                raise ValueError(
                    f"CORS_ORIGINS entries must be exact origins like https://app.example.com "
                    f"(scheme and host, optional port, no path, no wildcard); got {origin!r}"
                )
        return value

    @field_validator("demo_password")
    @classmethod
    def _demo_password_policy(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            validate_new_password(value.get_secret_value())
        return value

    @property
    def text_turns_enabled(self) -> bool:
        """The typed-turn endpoint exists for development and tests only."""
        return self.environment is not Environment.PRODUCTION


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
