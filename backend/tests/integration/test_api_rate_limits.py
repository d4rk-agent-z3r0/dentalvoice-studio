# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Rate limits through the real app: sign-in per client and per account, requests and writes."""

import secrets
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.rate_limits import RequestLimits
from app.core.config import Settings
from app.core.passwords import hash_password
from app.core.rate_limit import RateLimiter
from app.domain.enums import ClinicRole
from app.main import create_app
from app.models import ClinicUser, User
from tests.integration.conftest import ClinicFactory
from tests.support.api import bearer
from tests.support.booking import headers_for

pytestmark = pytest.mark.integration

SessionFactory = async_sessionmaker[AsyncSession]


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


AppClient = Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]]


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def app_client(database_settings: Settings, clock: Clock) -> AppClient:
    """A client for an app with the given rate-limit settings and a controllable clock."""

    @asynccontextmanager
    async def _client(**overrides: Any) -> AsyncIterator[httpx.AsyncClient]:
        settings = database_settings.model_copy(update=overrides)
        app = create_app(settings)
        app.state.request_limits = RequestLimits(settings, RateLimiter(clock))
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                yield client

    return _client


async def _account(session_factory: SessionFactory, clinic_id: uuid.UUID, password: str) -> str:
    email = f"person-{uuid.uuid4().hex[:12]}@example.org"
    async with session_factory.begin() as session:
        user = User(email=email, display_name="Test", password_hash=hash_password(password))
        session.add(user)
        await session.flush()
        session.add(ClinicUser(clinic_id=clinic_id, user_id=user.id, role=ClinicRole.STAFF))
    return email


async def _login(client: httpx.AsyncClient, email: str, password: str) -> httpx.Response:
    return await client.post("/api/v1/auth/login", json={"email": email, "password": password})


def _assert_limited(response: httpx.Response) -> None:
    assert response.status_code == 429, response.text
    error = response.json()["error"]
    assert error["code"] == "RATE_LIMITED"
    assert int(response.headers["retry-after"]) == error["retry_after_seconds"] >= 1


async def test_sign_in_attempts_are_limited_per_client(
    app_client: AppClient, session_factory: SessionFactory, make_clinic: ClinicFactory
) -> None:
    clinic = await make_clinic()
    password = secrets.token_urlsafe(18)
    email = await _account(session_factory, clinic.id, password)
    async with app_client(rate_login_per_ip_per_minute=3) as client:
        for i in range(3):  # different accounts: the client's own budget is what runs out
            response = await _login(client, f"nobody-{i}@example.com", password)
            assert response.status_code == 401
        refused = await _login(client, email, password)
    _assert_limited(refused)
    assert refused.json()["error"]["retry_after_seconds"] == 20  # 60 s / 3


async def test_an_account_locks_after_repeated_failures_even_for_the_right_password(
    app_client: AppClient,
    session_factory: SessionFactory,
    make_clinic: ClinicFactory,
    clock: Clock,
) -> None:
    clinic = await make_clinic()
    password = secrets.token_urlsafe(18)
    target = await _account(session_factory, clinic.id, password)
    bystander = await _account(session_factory, clinic.id, password)
    async with app_client(rate_login_failures_per_account=2) as client:
        for _ in range(2):
            assert (await _login(client, target, password + "x")).status_code == 401
        _assert_limited(await _login(client, target, password))  # guessing has stopped
        _assert_limited(await _login(client, target.upper(), password))  # same account
        assert (await _login(client, bystander, password)).status_code == 200
        clock.now += 15 * 60 / 2  # one failure's worth of the 15-minute window
        assert (await _login(client, target, password)).status_code == 200


async def test_a_successful_sign_in_clears_earlier_failures(
    app_client: AppClient, session_factory: SessionFactory, make_clinic: ClinicFactory
) -> None:
    clinic = await make_clinic()
    password = secrets.token_urlsafe(18)
    email = await _account(session_factory, clinic.id, password)
    async with app_client(rate_login_failures_per_account=2) as client:
        assert (await _login(client, email, password + "x")).status_code == 401
        assert (await _login(client, email, password)).status_code == 200
        assert (await _login(client, email, password + "x")).status_code == 401
        assert (await _login(client, email, password)).status_code == 200


async def test_requests_are_limited_per_user(
    app_client: AppClient,
    session_factory: SessionFactory,
    database_settings: Settings,
    make_clinic: ClinicFactory,
) -> None:
    clinic = await make_clinic()
    one = await headers_for(session_factory, database_settings, clinic.id, ClinicRole.VIEWER)
    two = await headers_for(session_factory, database_settings, clinic.id, ClinicRole.VIEWER)
    async with app_client(rate_requests_per_user_per_minute=3) as client:
        for _ in range(3):
            assert (await client.get("/api/v1/clinic", headers=one)).status_code == 200
        _assert_limited(await client.get("/api/v1/clinic", headers=one))
        assert (await client.get("/api/v1/clinic", headers=two)).status_code == 200


async def test_writes_have_their_own_tighter_limit(
    app_client: AppClient,
    session_factory: SessionFactory,
    database_settings: Settings,
    make_clinic: ClinicFactory,
) -> None:
    clinic = await make_clinic()
    staff = await headers_for(session_factory, database_settings, clinic.id, ClinicRole.STAFF)
    body = {"scenario_id": str(uuid.uuid4())}
    async with app_client(rate_writes_per_user_per_minute=2) as client:
        for _ in range(2):  # counted even though each is refused (unknown scenario)
            response = await client.post("/api/v1/conversations", json=body, headers=staff)
            assert response.status_code == 404
        _assert_limited(await client.post("/api/v1/conversations", json=body, headers=staff))
        assert (await client.get("/api/v1/clinic", headers=staff)).status_code == 200  # reads


async def test_an_invalid_token_is_refused_before_it_can_use_a_budget(
    app_client: AppClient,
) -> None:
    async with app_client(rate_requests_per_user_per_minute=1) as client:
        for _ in range(3):
            response = await client.get("/api/v1/clinic", headers=bearer("not.a.token"))
            assert response.status_code == 401


async def test_limits_can_be_switched_off(
    app_client: AppClient,
    session_factory: SessionFactory,
    database_settings: Settings,
    make_clinic: ClinicFactory,
) -> None:
    clinic = await make_clinic()
    viewer = await headers_for(session_factory, database_settings, clinic.id, ClinicRole.VIEWER)
    async with app_client(rate_limits_enabled=False, rate_requests_per_user_per_minute=1) as client:
        for _ in range(5):
            assert (await client.get("/api/v1/clinic", headers=viewer)).status_code == 200
