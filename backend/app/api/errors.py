# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""One error shape for every failure: ``{"error": {"code", "message", "request_id", ...}}``."""

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.security import AuthError
from app.domain.errors import DomainError
from app.integrations.llm.base import ProviderError, ProviderUnavailableError

_DOMAIN_STATUS = {
    "FORBIDDEN": 403,
    "NOT_FOUND": 404,
    "INVALID_STATE_TRANSITION": 400,
    "CONVERSATION_CLOSED": 409,
    "CONCURRENT_UPDATE": 409,
    "DUPLICATE_PATIENT": 409,
}


def error_body(code: str, message: str, **extra: Any) -> dict[str, Any]:
    request_id = structlog.contextvars.get_contextvars().get("request_id")
    return {"error": {"code": code, "message": message, "request_id": request_id, **extra}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain(_: Request, error: DomainError) -> JSONResponse:
        status = _DOMAIN_STATUS.get(error.code, 400)
        return JSONResponse(error_body(error.code, error.message), status_code=status)

    @app.exception_handler(AuthError)
    async def _auth(_: Request, error: AuthError) -> JSONResponse:
        status = 503 if error.code == "AUTH_NOT_CONFIGURED" else 401
        headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
        return JSONResponse(error_body(error.code, error.message), status, headers=headers)

    @app.exception_handler(ProviderError)
    async def _provider(_: Request, error: ProviderError) -> JSONResponse:
        unavailable = isinstance(error, ProviderUnavailableError)
        message = (
            "The conversation provider is temporarily unavailable. Please try again."
            if unavailable
            else "The conversation provider failed."
        )
        body = error_body(error.code, message, provider=error.provider)
        return JSONResponse(body, status_code=503 if unavailable else 502)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, error: RequestValidationError) -> JSONResponse:
        # Locations and messages only: never echo submitted input back.
        details = [
            {"loc": [str(part) for part in item.get("loc", ())], "msg": item.get("msg", "")}
            for item in error.errors()
        ]
        body = error_body("VALIDATION_ERROR", "The request is invalid.", details=details)
        return JSONResponse(body, status_code=400)
