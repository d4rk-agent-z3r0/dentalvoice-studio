# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Bounded retry of transactions PostgreSQL aborted to resolve a conflict."""

import pytest
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.database.retry import retry_transaction
from app.domain.errors import ConcurrentUpdateError


class _DriverError(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


def _error(sqlstate: str, kind: type[DBAPIError] = DBAPIError) -> DBAPIError:
    return kind("INSERT ...", {}, _DriverError(sqlstate))


class _Operation:
    def __init__(self, *failures: DBAPIError) -> None:
        self.failures = list(failures)
        self.calls = 0

    async def __call__(self) -> str:
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return "committed"


async def _no_wait(_: float) -> None:
    return None


@pytest.mark.parametrize("sqlstate", ["40P01", "40001"])
async def test_a_conflict_runs_the_whole_transaction_again(sqlstate: str) -> None:
    pauses: list[float] = []

    async def record(seconds: float) -> None:
        pauses.append(seconds)

    operation = _Operation(_error(sqlstate), _error(sqlstate))
    assert await retry_transaction(operation, attempts=3, sleep=record) == "committed"
    assert operation.calls == 3
    assert len(pauses) == 2
    assert all(0 <= p <= 0.05 * (i + 1) for i, p in enumerate(pauses))


async def test_running_out_of_attempts_is_a_concurrent_update() -> None:
    operation = _Operation(*(_error("40P01") for _ in range(3)))
    with pytest.raises(ConcurrentUpdateError) as caught:
        await retry_transaction(operation, attempts=3, sleep=_no_wait)
    assert operation.calls == 3
    assert isinstance(caught.value.__cause__, DBAPIError)


@pytest.mark.parametrize(
    "error",
    [_error("23P01", IntegrityError), _error("23505", IntegrityError), _error("57014")],
    ids=["exclusion", "unique", "query-cancelled"],
)
async def test_other_database_errors_are_not_retried(error: DBAPIError) -> None:
    operation = _Operation(error)
    with pytest.raises(type(error)) as caught:
        await retry_transaction(operation, attempts=3, sleep=_no_wait)
    assert caught.value is error
    assert operation.calls == 1


async def test_attempts_must_be_positive() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        await retry_transaction(_Operation(), attempts=0)
