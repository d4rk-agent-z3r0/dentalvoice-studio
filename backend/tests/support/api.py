# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Seeded demo world + authenticated HTTP clients for API tests."""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.security import Principal, issue_access_token
from app.domain.enums import ClinicRole
from app.models import Clinic, ClinicUser, SyntheticScenario, User


@dataclass(frozen=True)
class DemoClinic:
    id: uuid.UUID
    slug: str
    timezone: str
    scenarios: dict[str, uuid.UUID]  # code -> id


async def load_clinic(session_factory: async_sessionmaker[AsyncSession], slug: str) -> DemoClinic:
    async with session_factory() as session:
        clinic = await session.scalar(select(Clinic).where(Clinic.slug == slug))
        assert clinic is not None, f"seed first: {slug}"
        rows = await session.execute(
            select(SyntheticScenario.code, SyntheticScenario.id).where(
                SyntheticScenario.clinic_id == clinic.id
            )
        )
        scenarios = dict(rows.all())
        return DemoClinic(clinic.id, clinic.slug, clinic.timezone, scenarios)


async def token_for(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    email: str,
    clinic_id: uuid.UUID,
) -> str:
    async with session_factory() as session:
        row = (
            await session.execute(
                select(User.id, ClinicUser.role)
                .join(ClinicUser, ClinicUser.user_id == User.id)
                .where(User.email == email, ClinicUser.clinic_id == clinic_id)
            )
        ).one()
    return issue_access_token(settings, Principal(row[0], clinic_id, ClinicRole(row[1])))


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
