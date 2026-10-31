# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
from fastapi import APIRouter

from app.api.deps import CurrentPrincipal, SessionFactory
from app.schemas.scenario import ScenarioRead
from app.services.scenarios import ScenarioService

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


@router.get("", response_model=list[ScenarioRead])
async def list_scenarios(
    principal: CurrentPrincipal, session_factory: SessionFactory
) -> list[ScenarioRead]:
    return await ScenarioService(session_factory).list(principal.clinic_id)
