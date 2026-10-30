# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Liveness and readiness probes."""

import asyncio
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from app.core.logging import get_logger
from app.database.session import ping

router = APIRouter(prefix="/health", tags=["health"])
log = get_logger(__name__)

READINESS_TIMEOUT_SECONDS = 3.0


class LiveResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ReadyResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    database: Literal["ok", "unavailable"]


@router.get("/live", response_model=LiveResponse)
async def live() -> LiveResponse:
    return LiveResponse()


@router.get(
    "/ready",
    response_model=ReadyResponse,
    responses={503: {"model": ReadyResponse}},
)
async def ready(request: Request) -> ReadyResponse | JSONResponse:
    try:
        await asyncio.wait_for(ping(request.app.state.engine), READINESS_TIMEOUT_SECONDS)
    except (SQLAlchemyError, OSError, TimeoutError) as exc:
        log.warning("readiness_database_unavailable", error_type=type(exc).__name__)
        body = ReadyResponse(status="unavailable", database="unavailable")
        return JSONResponse(status_code=503, content=body.model_dump())
    return ReadyResponse(status="ok", database="ok")
