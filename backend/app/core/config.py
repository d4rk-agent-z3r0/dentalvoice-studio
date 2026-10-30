"""Application settings, loaded once from the environment."""

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class ProviderMode(StrEnum):
    MOCK = "mock"
    LIVE = "live"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    environment: Environment = Environment.DEVELOPMENT
    # Required: no default so credentials never live in source.
    database_url: PostgresDsn
    voice_provider_mode: ProviderMode = ProviderMode.MOCK
    log_level: str = "INFO"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_connect_timeout_seconds: float = Field(default=3.0, gt=0)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
