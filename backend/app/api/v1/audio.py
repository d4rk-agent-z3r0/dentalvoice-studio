# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Synthetic caller clips for browser playback.

Allow-listed: a clip id must exist in the scenario catalogue *and* belong to one of the
requesting clinic's scenarios. Anything else is a plain 404. Ids are looked up, never used as
paths.
"""

from typing import Annotated

from fastapi import APIRouter, Path
from fastapi.responses import FileResponse

from app.api.deps import CurrentPrincipal, SessionFactory
from app.domain.errors import NotFoundError
from app.repositories.scenarios import ScenarioRepository
from app.voice.clips import UnknownClipError, default_library

router = APIRouter(prefix="/audio", tags=["audio"])

ClipId = Annotated[str, Path(pattern=r"^[a-z]{1,2}-\d{2}$", max_length=8)]


@router.get(
    "/clips/{clip_id}",
    response_class=FileResponse,
    responses={200: {"content": {"audio/wav": {}}}},
)
async def get_clip(
    clip_id: ClipId, principal: CurrentPrincipal, session_factory: SessionFactory
) -> FileResponse:
    async with session_factory() as session:
        allowed = await ScenarioRepository(session).clinic_has_clip(principal.clinic_id, clip_id)
    if not allowed:
        raise NotFoundError("Clip")
    try:
        clip = default_library().get(clip_id)
    except UnknownClipError as error:
        raise NotFoundError("Clip") from error
    return FileResponse(
        clip.path,
        media_type="audio/wav",
        headers={"Cache-Control": "private, max-age=3600", "X-Clip-Source": clip.source},
    )
