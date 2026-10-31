# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Publishing bookable slots from weekly schedules.

Schedules are clinic-local wall-clock times; slots are stored in UTC. Conversion goes through
``zoneinfo`` per date, so a daylight-saving change moves the UTC instants but never the local
opening hours.
"""

import uuid
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppointmentSlot, DentistSchedule

SLOT_MINUTES = 15


@dataclass(frozen=True)
class WeeklyWindow:
    weekday: int  # Monday = 0
    start_local: time
    end_local: time


def slot_bounds(
    windows: Iterable[WeeklyWindow],
    timezone: str,
    first_day: date,
    days: int,
    slot_minutes: int = SLOT_MINUTES,
) -> Iterator[tuple[datetime, datetime]]:
    """UTC (start, end) pairs for every whole slot inside the windows, day by day."""
    zone = ZoneInfo(timezone)
    step = timedelta(minutes=slot_minutes)
    by_weekday: dict[int, list[WeeklyWindow]] = {}
    for window in windows:
        by_weekday.setdefault(window.weekday, []).append(window)
    for offset in range(days):
        day = first_day + timedelta(days=offset)
        for window in sorted(by_weekday.get(day.weekday(), []), key=lambda w: w.start_local):
            cursor = datetime.combine(day, window.start_local)
            end = datetime.combine(day, window.end_local)
            while cursor + step <= end:
                start_utc = cursor.replace(tzinfo=zone).astimezone(UTC)
                end_utc = (cursor + step).replace(tzinfo=zone).astimezone(UTC)
                yield start_utc, end_utc
                cursor += step


async def publish_slots(
    session: AsyncSession,
    clinic_id: uuid.UUID,
    timezone: str,
    first_day: date,
    days: int,
) -> int:
    """Publish open slots for every dentist's schedule. Idempotent: existing blocks are kept.

    Returns the number of new slots. Overlaps are skipped by the exclusion constraint
    (``ON CONFLICT DO NOTHING``), so re-running never duplicates or overlaps a block.
    """
    schedules = (
        await session.scalars(select(DentistSchedule).where(DentistSchedule.clinic_id == clinic_id))
    ).all()
    by_dentist: dict[uuid.UUID, list[WeeklyWindow]] = {}
    for row in schedules:
        by_dentist.setdefault(row.dentist_id, []).append(
            WeeklyWindow(row.weekday, row.start_local, row.end_local)
        )
    rows = [
        {"clinic_id": clinic_id, "dentist_id": dentist_id, "starts_at": start, "ends_at": end}
        for dentist_id, windows in by_dentist.items()
        for start, end in slot_bounds(windows, timezone, first_day, days)
    ]
    if not rows:
        return 0
    inserted = 0
    for batch_start in range(0, len(rows), 1000):
        stmt = (
            insert(AppointmentSlot)
            .values(rows[batch_start : batch_start + 1000])
            .on_conflict_do_nothing()
            .returning(AppointmentSlot.id)
        )
        inserted += len((await session.scalars(stmt)).all())
    return inserted
