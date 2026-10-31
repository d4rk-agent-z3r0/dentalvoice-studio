# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""In-process token-bucket rate limiting.

A bucket holds up to ``limit.capacity`` tokens and refills continuously at ``capacity`` per
``limit.window_seconds``, so short bursts are allowed and the long-run rate is bounded. State
lives in this process: this is a single-process demo (docs/security/threat-model.md). Several
replicas would need a shared store. Keys are bounded (least recently used evicted), so a flood of
distinct keys cannot exhaust memory. Keys are opaque strings; callers hash anything personal.
"""

import hashlib
import math
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

from app.domain.errors import DomainError


@dataclass(frozen=True)
class Limit:
    capacity: int
    window_seconds: float

    @property
    def refill_per_second(self) -> float:
        return self.capacity / self.window_seconds


class RateLimitedError(DomainError):
    code = "RATE_LIMITED"

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("Too many requests. Try again later.")
        self.retry_after_seconds = retry_after_seconds


@dataclass
class _Bucket:
    tokens: float
    updated: float


def opaque(value: str) -> str:
    """A stable, non-reversible key for a personal value (e.g. an email), so it is never held."""
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()[:32]


class RateLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic, max_keys: int = 50_000) -> None:
        self._clock = clock
        self._max_keys = max_keys
        self._buckets: OrderedDict[str, _Bucket] = OrderedDict()

    def _bucket(self, key: str, limit: Limit) -> _Bucket:
        now = self._clock()
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = _Bucket(tokens=float(limit.capacity), updated=now)
            self._buckets[key] = bucket
            while len(self._buckets) > self._max_keys:
                self._buckets.popitem(last=False)
        else:
            elapsed = max(0.0, now - bucket.updated)
            bucket.tokens = min(limit.capacity, bucket.tokens + elapsed * limit.refill_per_second)
            bucket.updated = now
            self._buckets.move_to_end(key)
        return bucket

    def check(self, key: str, limit: Limit) -> None:
        """Raise ``RateLimitedError`` if a request now would be refused; consume nothing."""
        bucket = self._bucket(key, limit)
        if bucket.tokens < 1:
            raise RateLimitedError(_retry_after(bucket, limit))

    def hit(self, key: str, limit: Limit) -> None:
        """Consume one token, or raise ``RateLimitedError`` (consuming nothing)."""
        bucket = self._bucket(key, limit)
        if bucket.tokens < 1:
            raise RateLimitedError(_retry_after(bucket, limit))
        bucket.tokens -= 1

    def reset(self, key: str) -> None:
        self._buckets.pop(key, None)


def _retry_after(bucket: _Bucket, limit: Limit) -> int:
    return max(1, math.ceil((1 - bucket.tokens) / limit.refill_per_second))
