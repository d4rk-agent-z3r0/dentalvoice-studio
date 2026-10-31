# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""The Alembic history is the only way the schema is built; these tests keep it honest."""

from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

from app.models import Base
from tests.support import alembic
from tests.support.database import create_test_engine, scratch_database

pytestmark = pytest.mark.integration


def _schema_diff(connection: Connection) -> list[Any]:
    context = MigrationContext.configure(
        connection, opts={"compare_type": True, "compare_server_default": True}
    )
    return list(compare_metadata(context, Base.metadata))


def _public_tables(connection: Connection) -> set[str]:
    return set(inspect(connection).get_table_names()) - {"alembic_version"}


async def test_upgrade_matches_models_and_downgrade_is_clean(test_database_url: str) -> None:
    async with scratch_database(test_database_url) as url:
        engine = create_test_engine(url)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(alembic.upgrade, "head")
                assert await connection.run_sync(_schema_diff) == []
                assert await connection.run_sync(_public_tables) == set(Base.metadata.tables)

            async with engine.begin() as connection:
                await connection.run_sync(alembic.downgrade, "base")
                assert await connection.run_sync(_public_tables) == set()
                extension = await connection.scalar(
                    text("SELECT count(*) FROM pg_extension WHERE extname = 'btree_gist'")
                )
                assert extension == 0

            # The full cycle can be repeated: downgrade leaves nothing behind that blocks upgrade.
            async with engine.begin() as connection:
                await connection.run_sync(alembic.upgrade, "head")
                assert await connection.run_sync(_schema_diff) == []
        finally:
            await engine.dispose()
