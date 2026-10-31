# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Pure slot maths: no I/O, every instant timezone-aware.

All arithmetic happens on UTC instants. Clinic-local wall-clock time is used only to turn a local
calendar date into the UTC instants that bound it, so a daylight-saving change (a 23- or 25-hour
day) never shifts or drops a bookable block.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.domain.enums import SlotStatus


@dataclass(frozen=True)
class Block:
    """One published slot (or any half-open ``[starts_at, ends_at)`` interval) of a dentist."""

    dentist_id: uuid.UUID
    starts_at: datetime
    ends_at: datetime
    status: SlotStatus = SlotStatus.OPEN


@dataclass(frozen=True)
class Window:
    """Half-open UTC interval ``[start, end)``."""

    start: datetime
    end: datetime


def local_days_window(first_day: date, days: int, timezone: str) -> Window:
    """UTC bounds of ``days`` consecutive clinic-local calendar days starting at ``first_day``.

    Local midnight is resolved per date, so the window of a DST-change day is 23 or 25 hours long.
    """
    if days < 1:
        raise ValueError("days must be at least 1")
    zone = ZoneInfo(timezone)
    start = datetime.combine(first_day, time(0), tzinfo=zone).astimezone(UTC)
    end = datetime.combine(first_day + timedelta(days=days), time(0), tzinfo=zone).astimezone(UTC)
    return Window(start, end)


def _overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


def covers_exactly(blocks: Iterable[Block], start: datetime, end: datetime) -> bool:
    """True if open blocks tile ``[start, end)`` exactly: contiguous, no gaps, whole blocks only.

    ``blocks`` are every slot of one dentist that overlaps the interval. A blocked slot, a gap, or
    a slot sticking out past either end means the interval is not bookable.
    """
    ordered = sorted(blocks, key=lambda b: b.starts_at)
    if not ordered or ordered[0].starts_at != start or ordered[-1].ends_at != end:
        return False
    cursor = start
    for block in ordered:
        if block.status is not SlotStatus.OPEN or block.starts_at != cursor:
            return False
        cursor = block.ends_at
    return cursor == end


def bookable_starts(
    open_blocks: Iterable[Block],
    busy: Iterable[Block],
    duration: timedelta,
    *,
    window: Window,
    after: datetime,
) -> list[Block]:
    """Every ``[start, start + duration)`` a dentist could be booked for.

    A candidate starts at the beginning of an open block inside ``window`` and strictly after
    ``after`` (now), is tiled exactly by consecutive open blocks of the same dentist (see
    ``covers_exactly``), and overlaps none of that dentist's ``busy`` intervals (active
    appointments). Results are ordered by start time, then dentist.
    """
    if duration <= timedelta(0):
        raise ValueError("duration must be positive")
    by_dentist: dict[uuid.UUID, list[Block]] = {}
    for block in open_blocks:
        if block.status is SlotStatus.OPEN:
            by_dentist.setdefault(block.dentist_id, []).append(block)
    busy_by_dentist: dict[uuid.UUID, list[Block]] = {}
    for interval in busy:
        busy_by_dentist.setdefault(interval.dentist_id, []).append(interval)

    options: list[Block] = []
    for dentist_id, blocks in by_dentist.items():
        blocks.sort(key=lambda b: b.starts_at)
        taken = busy_by_dentist.get(dentist_id, [])
        for i, first in enumerate(blocks):
            start = first.starts_at
            if not (window.start <= start < window.end) or start <= after:
                continue
            target = start + duration
            cursor = first.ends_at
            j = i
            while cursor < target and j + 1 < len(blocks) and blocks[j + 1].starts_at == cursor:
                j += 1
                cursor = blocks[j].ends_at
            if cursor != target:
                continue  # a gap, a blocked slot, or a block that would be split
            if any(_overlaps(start, target, t.starts_at, t.ends_at) for t in taken):
                continue
            options.append(Block(dentist_id, start, target))
    options.sort(key=lambda b: (b.starts_at, b.dentist_id))
    return options
