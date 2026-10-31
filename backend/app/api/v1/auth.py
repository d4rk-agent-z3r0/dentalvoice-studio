# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Sign-in. ``login`` is the only ``/api/v1`` route that needs no token."""

from fastapi import APIRouter, Request, Response

from app.api.deps import CurrentPrincipal, CurrentSettings, SessionFactory
from app.api.rate_limits import client_ip, get_request_limits
from app.core.security import AuthError
from app.schemas.auth import LoginRequest, MeRead, SessionRead, SwitchClinicRequest
from app.services.auth import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=SessionRead)
async def login(
    request: Request,
    body: LoginRequest,
    session_factory: SessionFactory,
    settings: CurrentSettings,
    response: Response,
) -> SessionRead:
    response.headers["Cache-Control"] = "no-store"  # the body carries a token
    limits = get_request_limits(request)
    account = limits.login_attempt(client_ip(request), body.email)
    try:
        session = await AuthService(session_factory, settings).login(body.email, body.password)
    except AuthError:
        limits.login_failed(account)
        raise
    limits.login_succeeded(account)
    return session


@router.post("/switch-clinic", response_model=SessionRead)
async def switch_clinic(
    body: SwitchClinicRequest,
    principal: CurrentPrincipal,
    session_factory: SessionFactory,
    settings: CurrentSettings,
    response: Response,
) -> SessionRead:
    response.headers["Cache-Control"] = "no-store"
    return await AuthService(session_factory, settings).switch_clinic(principal, body.clinic_id)


@router.get("/me", response_model=MeRead)
async def me(
    principal: CurrentPrincipal, session_factory: SessionFactory, settings: CurrentSettings
) -> MeRead:
    return await AuthService(session_factory, settings).me(principal)
