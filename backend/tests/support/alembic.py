# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Run Alembic commands on an existing connection (no URL read from the environment)."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Connection

BACKEND_DIR = Path(__file__).resolve().parents[2]


def alembic_config(connection: Connection) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["connection"] = connection
    config.attributes["configure_logger"] = False  # keep the structured logging setup intact
    return config


def upgrade(connection: Connection, revision: str = "head") -> None:
    command.upgrade(alembic_config(connection), revision)


def downgrade(connection: Connection, revision: str = "base") -> None:
    command.downgrade(alembic_config(connection), revision)
