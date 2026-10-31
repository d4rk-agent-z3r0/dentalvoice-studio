# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Shared test fixtures."""

import os
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import PostgresDsn, SecretStr

from app.core.config import Environment, ProviderMode, Settings
from app.main import create_app

# Port 1 on loopback is never a PostgreSQL server: connections are refused immediately.
UNREACHABLE_DATABASE_URL = "postgresql+asyncpg://nobody:nothing@127.0.0.1:1/none"
# A fixed signing key for tests only; it protects nothing.
TEST_JWT_SECRET = "test-only-signing-key-not-a-secret-0123456789"

ClientFactory = Callable[[Settings], AbstractAsyncContextManager[httpx.AsyncClient]]


@asynccontextmanager
async def _running_client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    app: FastAPI = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


@pytest.fixture
def client_factory() -> ClientFactory:
    return _running_client


def make_test_settings(database_url: str, **overrides: Any) -> Settings:
    """Settings isolated from any .env file; explicit init values also beat stray env vars."""
    values: dict[str, Any] = {
        "environment": Environment.TEST,
        "database_url": PostgresDsn(database_url),
        "voice_provider_mode": ProviderMode.MOCK,
        "log_level": "INFO",
        "cors_origins": ["http://localhost:3000"],
        "db_connect_timeout_seconds": 1.0,
        "jwt_secret": SecretStr(TEST_JWT_SECRET),
        "voice_realtime_factor": 0.0,
        **overrides,
    }
    return Settings(_env_file=None, **values)


@pytest.fixture
def offline_settings() -> Settings:
    return make_test_settings(UNREACHABLE_DATABASE_URL)


@pytest.fixture
def database_settings() -> Settings:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail("TEST_DATABASE_URL must be set to run integration tests (see Makefile).")
    return make_test_settings(url, db_connect_timeout_seconds=3.0)
