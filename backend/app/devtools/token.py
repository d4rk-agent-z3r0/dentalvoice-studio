# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Issue an access token for a seeded demo user (development only).

    uv run python -m app.devtools.token --email demo.staff@example.com --clinic brightsmile

Prints the token on stdout. Membership is read from the database, so the token carries the role
the user actually holds in that clinic. Replaced by the login endpoint in Milestone 8.
"""

import argparse
import asyncio
import sys

from sqlalchemy import select

from app.core.config import Environment, get_settings
from app.core.security import Principal, issue_access_token
from app.database.session import create_engine, create_session_factory
from app.models import Clinic, ClinicUser, User


async def _token(email: str, clinic_slug: str) -> str:
    settings = get_settings()
    if settings.environment is Environment.PRODUCTION:
        raise SystemExit("Refusing to issue development tokens in production.")
    engine = create_engine(settings)
    try:
        async with create_session_factory(engine)() as session:
            row = (
                await session.execute(
                    select(User.id, Clinic.id, ClinicUser.role)
                    .join(ClinicUser, ClinicUser.user_id == User.id)
                    .join(Clinic, Clinic.id == ClinicUser.clinic_id)
                    .where(User.email == email.lower(), Clinic.slug == clinic_slug)
                )
            ).one_or_none()
    finally:
        await engine.dispose()
    if row is None:
        raise SystemExit(f"{email} is not a member of {clinic_slug}. Run `make seed` first?")
    user_id, clinic_id, role = row
    return issue_access_token(settings, Principal(user_id, clinic_id, role))


def main() -> None:
    parser = argparse.ArgumentParser(description="Issue a development access token.")
    parser.add_argument("--email", default="demo.staff@example.com")
    parser.add_argument("--clinic", default="brightsmile")
    args = parser.parse_args()
    sys.stdout.write(asyncio.run(_token(args.email, args.clinic)) + "\n")


if __name__ == "__main__":
    main()
