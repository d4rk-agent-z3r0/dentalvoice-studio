# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Re-run a whole transaction that PostgreSQL aborted to resolve a conflict between transactions.

PostgreSQL aborts one side of a deadlock (SQLSTATE ``40P01``) or a serialization failure
(``40001``) and documents that the right response is to retry the entire transaction. Concurrent
inserts against an exclusion constraint can deadlock this way: each finds the other's uncommitted
row and waits for it. On the retry the winner has committed, so the retry sees the real outcome
(for a booking: the constraint violation that becomes ``BOOKING_SLOT_TAKEN``).

Retries are bounded. When they run out, ``ConcurrentUpdateError`` (409) is raised rather than a raw
database error. Only these two SQLSTATEs are retried; every other error propagates unchanged.
"""

import asyncio
import random
from collections.abc import Awaitable, Callable

from sqlalchemy.exc import DBAPIError

from app.core.logging import get_logger
from app.domain.errors import ConcurrentUpdateError

log = get_logger(__name__)

DEADLOCK_DETECTED = "40P01"
SERIALIZATION_FAILURE = "40001"
_RETRYABLE = frozenset({DEADLOCK_DETECTED, SERIALIZATION_FAILURE})

Sleep = Callable[[float], Awaitable[None]]


def is_transaction_conflict(error: DBAPIError) -> bool:
    return getattr(error.orig, "sqlstate", None) in _RETRYABLE


async def retry_transaction[T](
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int,
    pause_seconds: float = 0.05,
    sleep: Sleep = asyncio.sleep,
) -> T:
    """Run ``operation`` (one complete transaction) up to ``attempts`` times."""
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    for attempt in range(1, attempts + 1):
        try:
            return await operation()
        except DBAPIError as error:
            if not is_transaction_conflict(error):
                raise
            sqlstate = getattr(error.orig, "sqlstate", None)
            log.warning("transaction_conflict", sqlstate=sqlstate, attempt=attempt)
            if attempt == attempts:
                raise ConcurrentUpdateError(
                    "Another change to the calendar happened at the same moment. Try again."
                ) from error
            # Jitter, so the transactions that collided do not collide again in lockstep.
            await sleep(random.uniform(0, pause_seconds * attempt))  # noqa: S311 - not security
    raise AssertionError("unreachable")
