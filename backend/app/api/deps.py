# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Request dependencies. The clinic for every request is read from the verified token only."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.rate_limits import get_request_limits
from app.core.config import Settings
from app.core.security import AuthError, Principal, decode_access_token
from app.domain.enums import ClinicRole
from app.domain.errors import ForbiddenError
from app.orchestrators.conversation import ConversationOrchestrator
from app.repositories.users import UserRepository

__all__ = ["ForbiddenError"]  # re-exported: routers import it from here


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    return factory


def get_orchestrator(request: Request) -> ConversationOrchestrator:
    orchestrator: ConversationOrchestrator = request.app.state.orchestrator
    return orchestrator


async def get_principal(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> Principal:
    """The verified token's principal, re-checked against the database on every request.

    A signature alone is not enough: a user who was deactivated, removed from the clinic or given
    another role since the token was issued is refused at once, not when the token expires.
    """
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AuthError("AUTH_REQUIRED", "A bearer access token is required.")
    principal = decode_access_token(settings, token.strip())
    # Limited before the database is touched; only a validly signed token gets this far.
    get_request_limits(request).request(principal.user_id)
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with session_factory() as session:
        role = await UserRepository(session).active_role(principal.user_id, principal.clinic_id)
    if role is not principal.role:
        raise AuthError("AUTH_INVALID", "This session is no longer valid. Sign in again.")
    return principal


def require_roles(*roles: ClinicRole) -> Callable[[Request, Principal], Awaitable[Principal]]:
    allowed = frozenset(roles)

    async def _check(
        request: Request, principal: Annotated[Principal, Depends(get_principal)]
    ) -> Principal:
        if principal.role not in allowed:
            raise ForbiddenError("Your role does not allow this action.")
        get_request_limits(request).write(principal.user_id)  # role-gated routes are the writes
        return principal

    return _check


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
Operator = Annotated[Principal, Depends(require_roles(ClinicRole.ADMIN, ClinicRole.STAFF))]
SessionFactory = Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)]
Orchestrator = Annotated[ConversationOrchestrator, Depends(get_orchestrator)]
CurrentSettings = Annotated[Settings, Depends(get_settings)]
