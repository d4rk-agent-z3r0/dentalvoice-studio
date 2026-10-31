# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Users and their clinic memberships. Users are global; a membership ties one to a clinic."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import ClinicRole
from app.models import Clinic, ClinicUser, User


@dataclass(frozen=True)
class MembershipRow:
    clinic_id: uuid.UUID
    clinic_name: str
    clinic_timezone: str
    role: ClinicRole


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def by_email(self, email: str) -> User | None:
        stmt = select(User).where(func.lower(User.email) == email.strip().lower())
        return await self._session.scalar(stmt)

    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def memberships(self, user_id: uuid.UUID) -> Sequence[MembershipRow]:
        stmt = (
            select(Clinic.id, Clinic.name, Clinic.timezone, ClinicUser.role)
            .join(ClinicUser, ClinicUser.clinic_id == Clinic.id)
            .where(ClinicUser.user_id == user_id)
            .order_by(Clinic.name, Clinic.id)
        )
        return [MembershipRow(*row) for row in (await self._session.execute(stmt)).all()]

    async def active_role(self, user_id: uuid.UUID, clinic_id: uuid.UUID) -> ClinicRole | None:
        """The user's role in the clinic, or None if the user is inactive or not a member."""
        stmt = (
            select(ClinicUser.role)
            .join(User, User.id == ClinicUser.user_id)
            .where(
                ClinicUser.user_id == user_id,
                ClinicUser.clinic_id == clinic_id,
                User.is_active.is_(True),
            )
        )
        return await self._session.scalar(stmt)
