# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Token-bucket arithmetic, with a fake clock."""

import pytest

from app.core.rate_limit import Limit, RateLimitedError, RateLimiter, opaque


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


FIVE_PER_MINUTE = Limit(capacity=5, window_seconds=60)


def test_a_burst_up_to_capacity_then_a_refusal_with_retry_after() -> None:
    clock = Clock()
    limiter = RateLimiter(clock)
    for _ in range(5):
        limiter.hit("k", FIVE_PER_MINUTE)
    with pytest.raises(RateLimitedError) as caught:
        limiter.hit("k", FIVE_PER_MINUTE)
    assert caught.value.code == "RATE_LIMITED"
    assert caught.value.retry_after_seconds == 12  # one token refills every 60 / 5 seconds


def test_tokens_refill_continuously_and_never_beyond_capacity() -> None:
    clock = Clock()
    limiter = RateLimiter(clock)
    for _ in range(5):
        limiter.hit("k", FIVE_PER_MINUTE)
    clock.now += 12
    limiter.hit("k", FIVE_PER_MINUTE)  # exactly one token back
    with pytest.raises(RateLimitedError):
        limiter.hit("k", FIVE_PER_MINUTE)
    clock.now += 3600  # a long pause refills to capacity, not more
    for _ in range(5):
        limiter.hit("k", FIVE_PER_MINUTE)
    with pytest.raises(RateLimitedError):
        limiter.hit("k", FIVE_PER_MINUTE)


def test_a_refused_hit_consumes_nothing() -> None:
    clock = Clock()
    limiter = RateLimiter(clock)
    for _ in range(5):
        limiter.hit("k", FIVE_PER_MINUTE)
    for _ in range(10):
        with pytest.raises(RateLimitedError):
            limiter.hit("k", FIVE_PER_MINUTE)
    clock.now += 12
    limiter.hit("k", FIVE_PER_MINUTE)  # hammering while refused did not extend the wait


def test_check_does_not_consume_and_reset_restores_capacity() -> None:
    limiter = RateLimiter(Clock())
    for _ in range(10):
        limiter.check("k", FIVE_PER_MINUTE)
    for _ in range(5):
        limiter.hit("k", FIVE_PER_MINUTE)
    with pytest.raises(RateLimitedError):
        limiter.check("k", FIVE_PER_MINUTE)
    limiter.reset("k")
    limiter.check("k", FIVE_PER_MINUTE)


def test_keys_are_independent() -> None:
    limiter = RateLimiter(Clock())
    for _ in range(5):
        limiter.hit("a", FIVE_PER_MINUTE)
    limiter.hit("b", FIVE_PER_MINUTE)
    with pytest.raises(RateLimitedError):
        limiter.hit("a", FIVE_PER_MINUTE)


def test_memory_is_bounded_by_evicting_the_least_recently_used_key() -> None:
    limiter = RateLimiter(Clock(), max_keys=3)
    one = Limit(capacity=1, window_seconds=60)
    for key in ("a", "b", "c"):
        limiter.hit(key, one)
    limiter.hit("d", one)  # evicts "a", the oldest
    limiter.hit("a", one)  # "a" starts fresh
    with pytest.raises(RateLimitedError):
        limiter.hit("d", one)
    assert len(limiter._buckets) == 3


def test_opaque_keys_hide_and_normalise_personal_values() -> None:
    key = opaque(" Someone@Example.com ")
    assert key == opaque("someone@example.com")
    assert "someone" not in key
    assert len(key) == 32
