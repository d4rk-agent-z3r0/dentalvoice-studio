# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Password hashing with argon2id (RFC 9106 "low memory" profile: t=3, m=64 MiB, p=4).

Hashing is deliberately expensive, so it runs in a worker thread (the event loop keeps serving)
and at most ``MAX_CONCURRENT_HASHES`` run at once: a burst of sign-in attempts queues instead of
exhausting CPU and memory. An unknown user is checked against a dummy hash, so a wrong email and a
wrong password take the same time and the response cannot reveal which accounts exist.
"""

import asyncio
import contextlib
import secrets
import weakref
from dataclasses import dataclass
from functools import cache

from argon2 import PasswordHasher, profiles
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_LENGTH = 12
MAX_LENGTH = 128  # bounds hashing work per attempt
MAX_CONCURRENT_HASHES = 4

_HASHER = PasswordHasher.from_parameters(profiles.RFC_9106_LOW_MEMORY)
# One semaphore per event loop: an asyncio primitive must not be shared between loops.
_SLOTS: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = (
    weakref.WeakKeyDictionary()
)


class WeakPasswordError(ValueError):
    pass


@dataclass(frozen=True)
class PasswordCheck:
    ok: bool
    needs_rehash: bool = False


def validate_new_password(password: str) -> None:
    if not MIN_LENGTH <= len(password) <= MAX_LENGTH:
        raise WeakPasswordError(f"A password must be {MIN_LENGTH} to {MAX_LENGTH} characters long.")
    if password.strip() != password:
        raise WeakPasswordError("A password must not start or end with whitespace.")


def hash_password(password: str, *, enforce_policy: bool = True) -> str:
    """``enforce_policy=False`` only to re-hash a password that has just been verified."""
    if enforce_policy:
        validate_new_password(password)
    return _HASHER.hash(password)


@cache
def _dummy_hash() -> str:
    return _HASHER.hash(secrets.token_urlsafe(32))


def _verify(stored: str | None, password: str) -> PasswordCheck:
    if stored is None or len(password) > MAX_LENGTH:
        with contextlib.suppress(VerificationError):
            _HASHER.verify(_dummy_hash(), password[:MAX_LENGTH])
        return PasswordCheck(ok=False)
    try:
        _HASHER.verify(stored, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return PasswordCheck(ok=False)
    return PasswordCheck(ok=True, needs_rehash=_HASHER.check_needs_rehash(stored))


async def verify_password(stored: str | None, password: str) -> PasswordCheck:
    """``stored`` is None for an unknown, inactive or password-less user: fails at the same cost."""
    loop = asyncio.get_running_loop()
    slots = _SLOTS.get(loop)
    if slots is None:
        slots = _SLOTS[loop] = asyncio.Semaphore(MAX_CONCURRENT_HASHES)
    async with slots:
        return await asyncio.to_thread(_verify, stored, password)
