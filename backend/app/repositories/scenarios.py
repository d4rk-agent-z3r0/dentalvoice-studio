# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SyntheticPersona, SyntheticScenario


class ScenarioRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self, clinic_id: uuid.UUID) -> Sequence[SyntheticScenario]:
        stmt = (
            select(SyntheticScenario)
            .where(SyntheticScenario.clinic_id == clinic_id)
            .order_by(SyntheticScenario.code)
        )
        return (await self._session.scalars(stmt)).all()

    async def get(self, clinic_id: uuid.UUID, scenario_id: uuid.UUID) -> SyntheticScenario | None:
        stmt = select(SyntheticScenario).where(
            SyntheticScenario.clinic_id == clinic_id, SyntheticScenario.id == scenario_id
        )
        return await self._session.scalar(stmt)

    async def get_persona(
        self, clinic_id: uuid.UUID, persona_id: uuid.UUID
    ) -> SyntheticPersona | None:
        stmt = select(SyntheticPersona).where(
            SyntheticPersona.clinic_id == clinic_id, SyntheticPersona.id == persona_id
        )
        return await self._session.scalar(stmt)
