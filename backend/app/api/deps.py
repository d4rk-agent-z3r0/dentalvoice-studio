# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Request dependencies. The clinic for every request is read from the verified token only."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.security import AuthError, Principal, decode_access_token
from app.domain.enums import ClinicRole
from app.domain.errors import DomainError
from app.orchestrators.conversation import ConversationOrchestrator


class ForbiddenError(DomainError):
    code = "FORBIDDEN"


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    return factory


def get_orchestrator(request: Request) -> ConversationOrchestrator:
    orchestrator: ConversationOrchestrator = request.app.state.orchestrator
    return orchestrator


def get_principal(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> Principal:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AuthError("AUTH_REQUIRED", "A bearer access token is required.")
    return decode_access_token(settings, token.strip())


def require_roles(*roles: ClinicRole) -> Callable[[Principal], Awaitable[Principal]]:
    allowed = frozenset(roles)

    async def _check(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
        if principal.role not in allowed:
            raise ForbiddenError("Your role does not allow this action.")
        return principal

    return _check


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
Operator = Annotated[Principal, Depends(require_roles(ClinicRole.ADMIN, ClinicRole.STAFF))]
SessionFactory = Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)]
Orchestrator = Annotated[ConversationOrchestrator, Depends(get_orchestrator)]
CurrentSettings = Annotated[Settings, Depends(get_settings)]
