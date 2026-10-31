# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Sign-in, clinic switching, "who am I", and the per-request membership check.

Each test creates its own users and clinics (random names), so the shared seeded demo users are
never modified.
"""

import logging
import secrets
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

import httpx
import jwt
import pytest
from argon2 import PasswordHasher
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.passwords import hash_password
from app.demo import catalog
from app.demo.seed import seed
from app.domain.enums import ClinicRole
from app.models import Clinic, ClinicUser, User
from tests.conftest import ClientFactory
from tests.integration.conftest import ClinicFactory
from tests.support.api import bearer

pytestmark = pytest.mark.integration

SessionFactory = async_sessionmaker[AsyncSession]
FAILED = {"code": "AUTH_FAILED", "message": "Email or password is incorrect."}


@dataclass(frozen=True)
class Account:
    id: uuid.UUID
    email: str


AccountFactory = Callable[..., Awaitable[Account]]


@pytest.fixture
def password() -> str:
    return secrets.token_urlsafe(18)  # generated per test run; never written anywhere


@pytest.fixture
async def client(
    client_factory: ClientFactory, database_settings: Settings
) -> AsyncIterator[httpx.AsyncClient]:
    async with client_factory(database_settings) as client:
        yield client


@pytest.fixture
def make_account(session_factory: SessionFactory) -> AccountFactory:
    async def _make(
        memberships: dict[uuid.UUID, ClinicRole],
        password_hash: str | None,
        *,
        active: bool = True,
    ) -> Account:
        email = f"person-{uuid.uuid4().hex[:12]}@example.org"
        async with session_factory.begin() as session:
            user = User(
                email=email,
                display_name="Test Person",
                password_hash=password_hash,
                is_active=active,
            )
            session.add(user)
            await session.flush()
            for clinic_id, role in memberships.items():
                session.add(ClinicUser(clinic_id=clinic_id, user_id=user.id, role=role))
        return Account(user.id, email)

    return _make


async def _login(client: httpx.AsyncClient, email: str, password: str) -> httpx.Response:
    return await client.post("/api/v1/auth/login", json={"email": email, "password": password})


async def _token(client: httpx.AsyncClient, email: str, password: str) -> str:
    response = await _login(client, email, password)
    assert response.status_code == 200, response.text
    token: str = response.json()["access_token"]
    return token


def _claims(token: str) -> dict[str, object]:
    claims: dict[str, object] = jwt.decode(token, options={"verify_signature": False})
    return claims


async def _two_clinics(make_clinic: ClinicFactory) -> tuple[Clinic, Clinic]:
    tag = uuid.uuid4().hex[:8]
    second = await make_clinic(f"Zeta {tag} Dental", "America/New_York")
    first = await make_clinic(f"Alpha {tag} Dental", "Europe/London")
    return first, second  # created out of order: the list must sort by name, not creation


# --- login ---------------------------------------------------------------------------------------


async def test_login_returns_a_token_for_the_first_clinic_and_lists_all(
    client: httpx.AsyncClient,
    make_clinic: ClinicFactory,
    make_account: AccountFactory,
    password: str,
) -> None:
    alpha, zeta = await _two_clinics(make_clinic)
    account = await make_account(
        {zeta.id: ClinicRole.STAFF, alpha.id: ClinicRole.ADMIN}, hash_password(password)
    )

    response = await _login(client, account.email, password)

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 60 * 60
    assert body["user"] == {
        "id": str(account.id),
        "email": account.email,
        "display_name": "Test Person",
    }
    assert body["clinics"] == [
        {"id": str(alpha.id), "name": alpha.name, "role": "admin"},
        {"id": str(zeta.id), "name": zeta.name, "role": "staff"},
    ]
    assert body["clinic"] == {"id": str(alpha.id), "name": alpha.name, "timezone": "Europe/London"}
    assert body["role"] == "admin"
    claims = _claims(body["access_token"])
    assert (claims["sub"], claims["clinic_id"], claims["role"]) == (
        str(account.id),
        str(alpha.id),
        "admin",
    )
    assert password not in response.text

    me = await client.get("/api/v1/auth/me", headers=bearer(body["access_token"]))
    assert me.status_code == 200
    assert me.json() == {k: body[k] for k in ("user", "clinic", "role", "clinics")}


async def test_email_is_matched_without_case_or_surrounding_space(
    client: httpx.AsyncClient,
    make_clinic: ClinicFactory,
    make_account: AccountFactory,
    password: str,
) -> None:
    clinic = await make_clinic()
    account = await make_account({clinic.id: ClinicRole.STAFF}, hash_password(password))
    response = await _login(client, f"  {account.email.upper()} ", password)
    assert response.status_code == 200
    assert response.json()["role"] == "staff"


async def test_every_sign_in_failure_looks_the_same(
    client: httpx.AsyncClient,
    make_clinic: ClinicFactory,
    make_account: AccountFactory,
    password: str,
) -> None:
    clinic = await make_clinic()
    stored = hash_password(password)
    member = {clinic.id: ClinicRole.STAFF}
    good = await make_account(member, stored)
    inactive = await make_account(member, stored, active=False)
    no_password = await make_account(member, None)
    no_clinic = await make_account({}, stored)

    attempts = {
        "wrong password": (good.email, password + "x"),
        "unknown email": (f"nobody-{uuid.uuid4().hex[:8]}@example.com", password),
        "inactive user": (inactive.email, password),
        "no password set": (no_password.email, password),
        "no clinic": (no_clinic.email, password),
    }
    for reason, (email, attempt) in attempts.items():
        response = await _login(client, email, attempt)
        assert response.status_code == 401, reason
        error = response.json()["error"]
        assert {k: error[k] for k in ("code", "message")} == FAILED, reason
        assert response.headers["www-authenticate"] == "Bearer", reason
        assert "access_token" not in response.text
    assert (await _login(client, good.email, password)).status_code == 200  # the control


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"email": "someone@example.com"},
        {"email": "someone@example.com", "password": ""},
        {"email": "someone@example.com", "password": "x" * 129},
        {"email": "someone@example.com", "password": "a-password-here", "clinic_id": "x"},
    ],
    ids=["empty", "no-password", "blank-password", "too-long", "extra-field"],
)
async def test_malformed_sign_in_is_a_validation_error_that_echoes_nothing(
    client: httpx.AsyncClient, body: dict[str, str]
) -> None:
    response = await client.post("/api/v1/auth/login", json=body)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    for value in body.values():
        if len(value) > 3:
            assert value not in response.text


async def test_sign_in_never_logs_the_password_or_the_email(
    client: httpx.AsyncClient,
    make_clinic: ClinicFactory,
    make_account: AccountFactory,
    password: str,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    clinic = await make_clinic()
    account = await make_account({clinic.id: ClinicRole.STAFF}, hash_password(password))
    caplog.set_level(logging.DEBUG)
    capsys.readouterr()

    await _login(client, account.email, password + "wrong")
    await _login(client, account.email, password)

    out = capsys.readouterr()
    logged = caplog.text + out.out + out.err
    assert "login_failed" in logged
    assert "login_succeeded" in logged
    assert password not in logged
    assert account.email not in logged


async def test_a_hash_with_old_parameters_is_upgraded_at_sign_in(
    client: httpx.AsyncClient,
    session_factory: SessionFactory,
    make_clinic: ClinicFactory,
    make_account: AccountFactory,
    password: str,
) -> None:
    clinic = await make_clinic()
    weak = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(password)
    account = await make_account({clinic.id: ClinicRole.STAFF}, weak)

    assert (await _login(client, account.email, password)).status_code == 200
    async with session_factory() as session:
        stored = await session.scalar(select(User.password_hash).where(User.id == account.id))
    assert stored is not None
    assert stored != weak
    assert stored.startswith("$argon2id$v=19$m=65536,t=3,p=4$")
    assert (await _login(client, account.email, password)).status_code == 200


async def test_the_seed_sets_the_demo_password_from_settings(
    client: httpx.AsyncClient, session_factory: SessionFactory, password: str
) -> None:
    await seed(session_factory, days=1, demo_password=password)
    for user in catalog.DEMO_USERS:
        response = await _login(client, user.email, password)
        assert response.status_code == 200, user.email
        assert {c["role"] for c in response.json()["clinics"]} == {
            role.value for role in user.roles.values()
        }
    # Re-seeding without a password leaves the passwords alone.
    await seed(session_factory, days=1)
    assert (await _login(client, catalog.DEMO_USERS[0].email, password)).status_code == 200


# --- switching clinic ----------------------------------------------------------------------------


async def test_switching_clinic_issues_a_token_for_that_clinic(
    client: httpx.AsyncClient,
    make_clinic: ClinicFactory,
    make_account: AccountFactory,
    password: str,
) -> None:
    alpha, zeta = await _two_clinics(make_clinic)
    account = await make_account(
        {alpha.id: ClinicRole.ADMIN, zeta.id: ClinicRole.VIEWER}, hash_password(password)
    )
    first = await _token(client, account.email, password)

    response = await client.post(
        "/api/v1/auth/switch-clinic", json={"clinic_id": str(zeta.id)}, headers=bearer(first)
    )

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["clinic"] == {"id": str(zeta.id), "name": zeta.name, "timezone": "America/New_York"}
    assert body["role"] == "viewer"
    second = body["access_token"]
    assert (_claims(second)["clinic_id"], _claims(second)["role"]) == (str(zeta.id), "viewer")
    # The new token reads the new clinic, with the role held there.
    clinic = await client.get("/api/v1/clinic", headers=bearer(second))
    assert clinic.json()["id"] == str(zeta.id)
    write = await client.post(
        "/api/v1/conversations", json={"scenario_id": str(uuid.uuid4())}, headers=bearer(second)
    )
    assert write.status_code == 403  # a viewer in this clinic, even though admin in the other


async def test_switching_to_a_clinic_you_do_not_belong_to_is_forbidden(
    client: httpx.AsyncClient,
    make_clinic: ClinicFactory,
    make_account: AccountFactory,
    password: str,
) -> None:
    mine, theirs = await _two_clinics(make_clinic)
    account = await make_account({mine.id: ClinicRole.ADMIN}, hash_password(password))
    token = await _token(client, account.email, password)
    for target in (theirs.id, uuid.uuid4()):
        response = await client.post(
            "/api/v1/auth/switch-clinic", json={"clinic_id": str(target)}, headers=bearer(token)
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_switching_needs_a_token(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/switch-clinic", json={"clinic_id": str(uuid.uuid4())}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


# --- the per-request membership check ------------------------------------------------------------


@pytest.mark.parametrize("change", ["deactivated", "removed from clinic", "role changed"])
async def test_a_token_stops_working_as_soon_as_access_changes(
    client: httpx.AsyncClient,
    session_factory: SessionFactory,
    make_clinic: ClinicFactory,
    make_account: AccountFactory,
    password: str,
    change: str,
) -> None:
    clinic = await make_clinic()
    account = await make_account({clinic.id: ClinicRole.STAFF}, hash_password(password))
    token = await _token(client, account.email, password)
    assert (await client.get("/api/v1/auth/me", headers=bearer(token))).status_code == 200

    async with session_factory.begin() as session:
        if change == "deactivated":
            await session.execute(update(User).where(User.id == account.id).values(is_active=False))
        elif change == "removed from clinic":
            await session.execute(delete(ClinicUser).where(ClinicUser.user_id == account.id))
        else:
            await session.execute(
                update(ClinicUser)
                .where(ClinicUser.user_id == account.id)
                .values(role=ClinicRole.VIEWER)
            )

    for path in ("/api/v1/auth/me", "/api/v1/scenarios", "/api/v1/conversations"):
        response = await client.get(path, headers=bearer(token))
        assert response.status_code == 401, path
        assert response.json()["error"]["code"] == "AUTH_INVALID"
