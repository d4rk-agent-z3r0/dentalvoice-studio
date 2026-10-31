# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Sign-in, clinic switching and "who am I". Tokens name one clinic; the database decides which.

Every failure to sign in is the same ``AUTH_FAILED`` (unknown email, wrong password, inactive
user, a user without a password or without any clinic), and costs the same password check, so
the response does not reveal which accounts exist. Passwords are never logged or returned.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.logging import get_logger
from app.core.passwords import hash_password, verify_password
from app.core.security import AuthError, Principal, issue_access_token
from app.domain.errors import ForbiddenError
from app.repositories.users import MembershipRow, UserRepository
from app.schemas.auth import Membership, MeRead, SessionClinic, SessionRead, UserRead

log = get_logger(__name__)

AUTH_FAILED_MESSAGE = "Email or password is incorrect."


class AuthService:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], settings: Settings
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings

    async def login(self, email: str, password: str) -> SessionRead:
        async with self._session_factory() as session:
            users = UserRepository(session)
            user = await users.by_email(email)
            stored = user.password_hash if user is not None and user.is_active else None
            check = await verify_password(stored, password)  # same cost when stored is None
            memberships = list(await users.memberships(user.id)) if user and check.ok else []
        if user is None or not check.ok or not memberships:
            log.info("login_failed")  # no email: it would make the log a list of attempted users
            raise AuthError("AUTH_FAILED", AUTH_FAILED_MESSAGE)
        if check.needs_rehash:
            await self._rehash(user.id, password)
        log.info("login_succeeded", user_id=str(user.id))
        return self._session(
            UserRead(id=user.id, email=user.email, display_name=user.display_name),
            memberships,
            memberships[0],
        )

    async def switch_clinic(self, principal: Principal, clinic_id: uuid.UUID) -> SessionRead:
        user, memberships = await self._load(principal.user_id)
        target = next((m for m in memberships if m.clinic_id == clinic_id), None)
        if target is None:
            raise ForbiddenError("You are not a member of that clinic.")
        log.info("clinic_switched", user_id=str(user.id), clinic_id=str(clinic_id))
        return self._session(user, memberships, target)

    async def me(self, principal: Principal) -> MeRead:
        user, memberships = await self._load(principal.user_id)
        current = next((m for m in memberships if m.clinic_id == principal.clinic_id), None)
        if current is None:  # the request dependency already checked; membership just removed
            raise AuthError("AUTH_INVALID", "This session is no longer valid. Sign in again.")
        return _me(user, memberships, current)

    async def _load(self, user_id: uuid.UUID) -> tuple[UserRead, list[MembershipRow]]:
        async with self._session_factory() as session:
            users = UserRepository(session)
            user = await users.get(user_id)
            if user is None or not user.is_active:
                raise AuthError("AUTH_INVALID", "This session is no longer valid. Sign in again.")
            memberships = list(await users.memberships(user_id))
            return UserRead(
                id=user.id, email=user.email, display_name=user.display_name
            ), memberships

    def _session(
        self, user: UserRead, memberships: list[MembershipRow], current: MembershipRow
    ) -> SessionRead:
        token = issue_access_token(
            self._settings, Principal(user.id, current.clinic_id, current.role)
        )
        return SessionRead(
            **_me(user, memberships, current).model_dump(),
            access_token=token,
            expires_in=self._settings.jwt_ttl_minutes * 60,
        )

    async def _rehash(self, user_id: uuid.UUID, password: str) -> None:
        """Upgrade a hash made with older parameters, now that the plain password is at hand."""
        async with self._session_factory.begin() as session:
            user = await UserRepository(session).get(user_id)
            if user is not None:
                user.password_hash = hash_password(password, enforce_policy=False)


def _me(user: UserRead, memberships: list[MembershipRow], current: MembershipRow) -> MeRead:
    return MeRead(
        user=user,
        clinic=SessionClinic(
            id=current.clinic_id, name=current.clinic_name, timezone=current.clinic_timezone
        ),
        role=current.role,
        clinics=[Membership(id=m.clinic_id, name=m.clinic_name, role=m.role) for m in memberships],
    )
