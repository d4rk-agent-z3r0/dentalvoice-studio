# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""GET /api/v1/clinic: the token's clinic and its booking reference data."""

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime

import httpx
import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.domain.enums import ClinicRole
from app.models import AppointmentType, Dentist
from app.services.clinics import ClinicService
from tests.conftest import ClientFactory
from tests.support.booking import build_booking_clinic, headers_for

pytestmark = pytest.mark.integration

SessionFactory = async_sessionmaker[AsyncSession]


@pytest.fixture
async def client(
    client_factory: ClientFactory, database_settings: Settings, session_factory: SessionFactory
) -> AsyncIterator[httpx.AsyncClient]:
    async with client_factory(database_settings) as http:
        yield http


async def test_returns_the_tokens_clinic_with_types_and_dentists(
    client: httpx.AsyncClient, session_factory: SessionFactory, database_settings: Settings
) -> None:
    clinic = await build_booking_clinic(session_factory)
    other = await build_booking_clinic(session_factory, timezone="America/New_York")
    async with session_factory.begin() as session:
        await session.execute(
            update(Dentist).where(Dentist.id == clinic.dentist_b).values(is_active=False)
        )
        await session.execute(
            update(AppointmentType)
            .where(AppointmentType.id == clinic.cleaning_id)
            .values(is_active=False)
        )

    response = await client.get(
        "/api/v1/clinic",
        headers=await headers_for(
            session_factory, database_settings, clinic.clinic_id, ClinicRole.VIEWER
        ),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(clinic.clinic_id)
    assert body["timezone"] == "Europe/London"
    assert date.fromisoformat(body["today"])  # a calendar day, not an instant
    # Inactive rows are listed (old appointments still need their names), flagged as such.
    assert body["appointment_types"] == [
        {
            "id": str(clinic.checkup_id),
            "code": "checkup",
            "name": "Check-up",
            "duration_minutes": 30,
            "is_active": True,
        },
        {
            "id": str(clinic.cleaning_id),
            "code": "hygiene_cleaning",
            "name": "Cleaning",
            "duration_minutes": 45,
            "is_active": False,
        },
    ]
    assert body["dentists"] == [
        {"id": str(clinic.dentist_a), "display_name": "Dr. Ada Example", "is_active": True},
        {"id": str(clinic.dentist_b), "display_name": "Dr. Bo Example", "is_active": False},
    ]
    assert str(other.dentist_a) not in response.text

    theirs = await client.get(
        "/api/v1/clinic",
        headers=await headers_for(
            session_factory, database_settings, other.clinic_id, ClinicRole.ADMIN
        ),
    )
    assert theirs.json()["id"] == str(other.clinic_id)
    assert theirs.json()["timezone"] == "America/New_York"
    assert (await client.get("/api/v1/clinic")).status_code == 401


async def test_today_is_the_clinic_local_date(session_factory: SessionFactory) -> None:
    clinic = await build_booking_clinic(session_factory, timezone="Pacific/Auckland")
    # 2026-10-31 20:00 UTC is already 1 November in Auckland (UTC+13).
    instant = datetime(2026, 10, 31, 20, 0, tzinfo=UTC)
    service = ClinicService(session_factory, clock=lambda: instant)
    assert (await service.get(clinic.clinic_id)).today == date(2026, 11, 1)
