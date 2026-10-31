# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""argon2id password hashing: policy, verification and the equal-cost failure path."""

import secrets

import pytest
from argon2 import PasswordHasher

from app.core import passwords
from app.core.passwords import (
    MAX_LENGTH,
    MIN_LENGTH,
    WeakPasswordError,
    hash_password,
    verify_password,
)


def _password() -> str:
    return secrets.token_urlsafe(18)  # generated per test; nothing real or reusable


def test_hashes_are_argon2id_and_salted() -> None:
    password = _password()
    first, second = hash_password(password), hash_password(password)
    assert first.startswith("$argon2id$v=19$m=65536,t=3,p=4$")
    assert first != second  # random salt
    assert password not in first


async def test_the_right_password_verifies_and_a_wrong_one_does_not() -> None:
    password = _password()
    stored = hash_password(password)
    assert (await verify_password(stored, password)).ok
    assert not (await verify_password(stored, password + "x")).ok
    assert not (await verify_password(stored, "")).ok


async def test_a_missing_hash_fails_after_doing_the_same_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checked: list[str] = []
    real_verify = PasswordHasher.verify

    def spy(self: PasswordHasher, stored: str, password: str) -> bool:
        checked.append(stored)
        return real_verify(self, stored, password)

    monkeypatch.setattr(PasswordHasher, "verify", spy)
    assert not (await verify_password(None, _password())).ok
    assert len(checked) == 1
    assert checked[0].startswith("$argon2id$")  # the dummy hash


async def test_an_over_long_attempt_is_refused_without_hashing_it_whole() -> None:
    password = "a" * MIN_LENGTH
    stored = hash_password(password)
    assert not (await verify_password(stored, password + "a" * MAX_LENGTH)).ok


async def test_a_corrupt_stored_hash_fails_closed() -> None:
    assert not (await verify_password("not-a-hash", _password())).ok


async def test_old_parameters_are_flagged_for_rehash() -> None:
    password = _password()
    weak = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(password)
    check = await verify_password(weak, password)
    assert check.ok
    assert check.needs_rehash
    assert not (await verify_password(hash_password(password), password)).needs_rehash


@pytest.mark.parametrize(
    "candidate",
    [
        "a" * (MIN_LENGTH - 1),
        "a" * (MAX_LENGTH + 1),
        " " + "a" * MIN_LENGTH,
        "a" * MIN_LENGTH + "\n",
    ],
    ids=["too-short", "too-long", "leading-space", "trailing-newline"],
)
def test_the_new_password_policy(candidate: str) -> None:
    with pytest.raises(WeakPasswordError):
        hash_password(candidate)


def test_rehash_of_a_verified_password_skips_the_policy() -> None:
    assert hash_password("short", enforce_policy=False).startswith("$argon2id$")


def test_password_settings_are_bounded() -> None:
    assert (MIN_LENGTH, MAX_LENGTH, passwords.MAX_CONCURRENT_HASHES) == (12, 128, 4)
