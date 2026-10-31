# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Database helpers for integration tests."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def create_test_engine(url: str) -> AsyncEngine:
    return create_async_engine(url, pool_size=10, max_overflow=10)


@asynccontextmanager
async def scratch_database(base_url: str) -> AsyncIterator[str]:
    """Create an empty, uniquely named database next to the test database; drop it afterwards."""
    url = make_url(base_url)
    name = f"{url.database}_scratch_{uuid.uuid4().hex[:8]}"
    admin = create_async_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{name}"'))
        try:
            yield url.set(database=name).render_as_string(hide_password=False)
        finally:
            async with admin.connect() as connection:
                await connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        await admin.dispose()
