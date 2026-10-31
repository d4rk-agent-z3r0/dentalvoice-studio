# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Availability maths: runs of open slots, exact cover, local-day windows across DST."""

import random
import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.domain.enums import SlotStatus
from app.services.booking.slots import (
    Block,
    Window,
    bookable_starts,
    covers_exactly,
    local_days_window,
)
from app.services.calendar import WeeklyWindow, slot_bounds

DR_A = uuid.UUID(int=1)
DR_B = uuid.UUID(int=2)
T0 = datetime(2030, 1, 7, 9, 0, tzinfo=UTC)
LONG_AGO = datetime(2000, 1, 1, tzinfo=UTC)
WHOLE_DAY = Window(datetime(2030, 1, 7, tzinfo=UTC), datetime(2030, 1, 8, tzinfo=UTC))
M15 = timedelta(minutes=15)
M30 = timedelta(minutes=30)


def run(dentist: uuid.UUID, start: datetime, count: int, minutes: int = 15) -> list[Block]:
    step = timedelta(minutes=minutes)
    return [Block(dentist, start + i * step, start + (i + 1) * step) for i in range(count)]


def starts(options: list[Block]) -> list[tuple[uuid.UUID, str]]:
    return [(o.dentist_id, o.starts_at.strftime("%H:%M")) for o in options]


@pytest.mark.parametrize(
    ("timezone", "day", "start", "hours"),
    [
        ("Europe/London", date(2026, 1, 12), datetime(2026, 1, 12, 0, 0, tzinfo=UTC), 24),
        ("Europe/London", date(2026, 7, 1), datetime(2026, 6, 30, 23, 0, tzinfo=UTC), 24),
        ("Europe/London", date(2026, 3, 29), datetime(2026, 3, 29, 0, 0, tzinfo=UTC), 23),
        ("Europe/London", date(2026, 10, 25), datetime(2026, 10, 24, 23, 0, tzinfo=UTC), 25),
        ("America/New_York", date(2026, 3, 8), datetime(2026, 3, 8, 5, 0, tzinfo=UTC), 23),
        ("America/New_York", date(2026, 11, 1), datetime(2026, 11, 1, 4, 0, tzinfo=UTC), 25),
    ],
)
def test_local_day_window_follows_the_clinic_calendar(
    timezone: str, day: date, start: datetime, hours: int
) -> None:
    window = local_days_window(day, 1, timezone)
    assert window.start == start
    assert window.end - window.start == timedelta(hours=hours)


def test_multi_day_window_spans_a_dst_change() -> None:
    window = local_days_window(date(2026, 10, 24), 3, "Europe/London")
    assert window.start == datetime(2026, 10, 23, 23, 0, tzinfo=UTC)
    assert window.end == datetime(2026, 10, 27, 0, 0, tzinfo=UTC)  # 24 + 25 + 24 hours


def test_window_needs_at_least_one_day() -> None:
    with pytest.raises(ValueError, match="days"):
        local_days_window(date(2026, 1, 1), 0, "Europe/London")


def test_covers_exactly() -> None:
    blocks = run(DR_A, T0, 2)
    assert covers_exactly(blocks, T0, T0 + M30)
    assert covers_exactly(reversed(blocks), T0, T0 + M30)  # order does not matter
    assert not covers_exactly([], T0, T0 + M30)
    assert not covers_exactly(blocks[:1], T0, T0 + M30)  # too short
    assert not covers_exactly(blocks, T0, T0 + M15)  # second block sticks out
    assert not covers_exactly(blocks, T0 + timedelta(minutes=5), T0 + M30)  # misaligned start
    gap = [blocks[0], Block(DR_A, T0 + M30, T0 + 3 * M15)]
    assert not covers_exactly(gap, T0, T0 + 3 * M15)
    blocked = [blocks[0], Block(DR_A, T0 + M15, T0 + M30, SlotStatus.BLOCKED)]
    assert not covers_exactly(blocked, T0, T0 + M30)


def test_every_start_inside_a_run_long_enough_is_offered() -> None:
    options = bookable_starts(run(DR_A, T0, 4), [], M30, window=WHOLE_DAY, after=LONG_AGO)
    assert starts(options) == [(DR_A, "09:00"), (DR_A, "09:15"), (DR_A, "09:30")]
    assert all(o.ends_at - o.starts_at == M30 for o in options)


def test_a_gap_or_blocked_slot_breaks_a_run() -> None:
    blocks = [*run(DR_A, T0, 2), *run(DR_A, T0 + timedelta(minutes=45), 2)]  # 09:30 missing
    options = bookable_starts(blocks, [], M30, window=WHOLE_DAY, after=LONG_AGO)
    assert starts(options) == [(DR_A, "09:00"), (DR_A, "09:45")]

    with_blocked = run(DR_A, T0, 3)
    with_blocked[1] = Block(DR_A, T0 + M15, T0 + M30, SlotStatus.BLOCKED)
    options = bookable_starts(with_blocked, [], M30, window=WHOLE_DAY, after=LONG_AGO)
    assert options == []


def test_active_appointments_remove_overlapping_starts_only() -> None:
    busy = [Block(DR_A, T0 + M30, T0 + 2 * M30)]  # 09:30-10:00
    options = bookable_starts(run(DR_A, T0, 8), busy, M30, window=WHOLE_DAY, after=LONG_AGO)
    # 09:00 ends exactly when the appointment starts; 10:00 starts exactly when it ends.
    assert starts(options) == [
        (DR_A, "09:00"),
        (DR_A, "10:00"),
        (DR_A, "10:15"),
        (DR_A, "10:30"),
    ]


def test_another_dentists_appointment_does_not_block() -> None:
    blocks = [*run(DR_A, T0, 2), *run(DR_B, T0, 2)]
    busy = [Block(DR_B, T0, T0 + M30)]
    options = bookable_starts(blocks, busy, M30, window=WHOLE_DAY, after=LONG_AGO)
    assert starts(options) == [(DR_A, "09:00")]


def test_options_are_ordered_by_time_then_dentist() -> None:
    blocks = [*run(DR_B, T0, 3), *run(DR_A, T0, 3)]
    options = bookable_starts(blocks, [], M30, window=WHOLE_DAY, after=LONG_AGO)
    assert starts(options) == [
        (DR_A, "09:00"),
        (DR_B, "09:00"),
        (DR_A, "09:15"),
        (DR_B, "09:15"),
    ]


def test_only_future_starts_are_offered() -> None:
    blocks = run(DR_A, T0, 4)
    options = bookable_starts(blocks, [], M30, window=WHOLE_DAY, after=T0 + M15)
    assert starts(options) == [(DR_A, "09:30")]  # 09:15 is "now", so not offered


def test_starts_must_lie_in_the_window_but_runs_may_finish_after_it() -> None:
    blocks = run(DR_A, T0, 4)
    window = Window(T0 + M15, T0 + M30 + timedelta(minutes=1))
    options = bookable_starts(blocks, [], M30, window=window, after=LONG_AGO)
    assert starts(options) == [(DR_A, "09:15"), (DR_A, "09:30")]


def test_a_longer_block_is_never_split() -> None:
    blocks = [Block(DR_A, T0, T0 + timedelta(minutes=75))]
    assert bookable_starts(blocks, [], M30, window=WHOLE_DAY, after=LONG_AGO) == []
    exact = bookable_starts(blocks, [], timedelta(minutes=75), window=WHOLE_DAY, after=LONG_AGO)
    assert starts(exact) == [(DR_A, "09:00")]


def test_blocked_slots_passed_as_open_input_are_ignored() -> None:
    blocks = [Block(DR_A, T0, T0 + M30, SlotStatus.BLOCKED)]
    assert bookable_starts(blocks, [], M30, window=WHOLE_DAY, after=LONG_AGO) == []


def test_duration_must_be_positive() -> None:
    with pytest.raises(ValueError, match="duration"):
        bookable_starts([], [], timedelta(0), window=WHOLE_DAY, after=LONG_AGO)


@pytest.mark.parametrize(
    ("first_day", "utc_hours", "offsets"),
    [
        # Saturday before and Sunday of the spring change: 09:00 local is 09:00Z, then 08:00Z.
        (date(2026, 3, 28), (9, 8), ("+00:00", "+01:00")),
        # Saturday before and Sunday of the autumn change: 09:00 local is 08:00Z, then 09:00Z.
        (date(2026, 10, 24), (8, 9), ("+01:00", "+00:00")),
    ],
)
def test_published_slots_stay_at_local_opening_hours_across_dst(
    first_day: date, utc_hours: tuple[int, int], offsets: tuple[str, str]
) -> None:
    timezone = "Europe/London"
    weekend = [WeeklyWindow(day, time(9, 0), time(10, 0)) for day in (5, 6)]
    blocks = [Block(DR_A, s, e) for s, e in slot_bounds(weekend, timezone, first_day, 2)]
    window = local_days_window(first_day, 2, timezone)

    options = bookable_starts(blocks, [], M30, window=window, after=LONG_AGO)

    assert len(options) == 6  # 09:00, 09:15, 09:30 on each day
    zone = ZoneInfo(timezone)
    local = [o.starts_at.astimezone(zone).isoformat() for o in options]
    sat, sun = first_day.isoformat(), (first_day + timedelta(days=1)).isoformat()
    assert local == [
        f"{sat}T09:00:00{offsets[0]}",
        f"{sat}T09:15:00{offsets[0]}",
        f"{sat}T09:30:00{offsets[0]}",
        f"{sun}T09:00:00{offsets[1]}",
        f"{sun}T09:15:00{offsets[1]}",
        f"{sun}T09:30:00{offsets[1]}",
    ]
    assert [options[0].starts_at.hour, options[3].starts_at.hour] == list(utc_hours)


def test_the_extra_hour_of_an_autumn_day_belongs_to_that_day() -> None:
    # 00:30 BST on 2026-10-25 is 23:30Z on the 24th; 23:30 GMT on the 25th is 23:30Z on the 25th.
    early = Block(
        DR_A, datetime(2026, 10, 24, 23, 30, tzinfo=UTC), datetime(2026, 10, 25, 0, 0, tzinfo=UTC)
    )
    late = Block(
        DR_A, datetime(2026, 10, 25, 23, 30, tzinfo=UTC), datetime(2026, 10, 26, 0, 0, tzinfo=UTC)
    )
    window = local_days_window(date(2026, 10, 25), 1, "Europe/London")

    options = bookable_starts([early, late], [], M30, window=window, after=LONG_AGO)

    assert [o.starts_at for o in options] == [early.starts_at, late.starts_at]
    next_day = local_days_window(date(2026, 10, 26), 1, "Europe/London")
    assert bookable_starts([early, late], [], M30, window=next_day, after=LONG_AGO) == []


@pytest.mark.parametrize("seed", range(25))
def test_offers_agree_with_the_reservation_cover_rule(seed: int) -> None:
    """Every offered time passes the rule a reservation enforces, and nothing that passes is
    missing, on random calendars with gaps, blocked slots, odd-length blocks and appointments."""
    rng = random.Random(seed)  # noqa: S311 - seeded test data, not a security use
    blocks: list[Block] = []
    for dentist in (DR_A, DR_B):
        cursor = T0
        for _ in range(30):
            cursor += timedelta(minutes=rng.choice((0, 0, 0, 15, 30)))
            length = timedelta(minutes=rng.choice((15, 15, 15, 15, 30, 45)))
            status = SlotStatus.BLOCKED if rng.random() < 0.1 else SlotStatus.OPEN
            blocks.append(Block(dentist, cursor, cursor + length, status))
            cursor += length
    busy = [Block(b.dentist_id, b.starts_at, b.starts_at + M30) for b in rng.sample(blocks, 4)]
    duration = timedelta(minutes=rng.choice((15, 30, 45, 60)))
    now = T0 + timedelta(minutes=rng.choice((0, 30, 90)))

    offered = {
        (o.dentist_id, o.starts_at)
        for o in bookable_starts(
            [b for b in blocks if b.status is SlotStatus.OPEN],
            busy,
            duration,
            window=WHOLE_DAY,
            after=now,
        )
    }

    expected = set()
    for candidate in blocks:
        start, end, dentist = (
            candidate.starts_at,
            candidate.starts_at + duration,
            candidate.dentist_id,
        )
        if start <= now or not WHOLE_DAY.start <= start < WHOLE_DAY.end:
            continue
        mine = [
            b for b in blocks if b.dentist_id == dentist and b.starts_at < end and b.ends_at > start
        ]
        clash = any(
            t.dentist_id == dentist and t.starts_at < end and start < t.ends_at for t in busy
        )
        if covers_exactly(mine, start, end) and not clash:
            expected.add((dentist, start))
    assert offered == expected
