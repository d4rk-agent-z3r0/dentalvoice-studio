# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import NotFoundError
from app.repositories.scenarios import ScenarioRepository
from app.schemas.scenario import PersonaRead, ScenarioRead


class ScenarioService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list(self, clinic_id: uuid.UUID) -> list[ScenarioRead]:
        async with self._session_factory() as session:
            rows = await ScenarioRepository(session).list(clinic_id)
            return [ScenarioRead.model_validate(row) for row in rows]

    async def get(self, clinic_id: uuid.UUID, scenario_id: uuid.UUID) -> ScenarioRead:
        async with self._session_factory() as session:
            row = await ScenarioRepository(session).get(clinic_id, scenario_id)
            if row is None:
                raise NotFoundError("Scenario")
            return ScenarioRead.model_validate(row)

    async def get_persona(self, clinic_id: uuid.UUID, persona_id: uuid.UUID) -> PersonaRead:
        async with self._session_factory() as session:
            row = await ScenarioRepository(session).get_persona(clinic_id, persona_id)
            if row is None:
                raise NotFoundError("Persona")
            return PersonaRead.model_validate(row)
