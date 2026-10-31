# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Which limits apply where. Keys never hold personal data: emails are hashed (``opaque``)."""

import uuid
from dataclasses import dataclass

from fastapi import Request

from app.core.config import Settings
from app.core.rate_limit import Limit, RateLimiter, opaque


@dataclass(frozen=True)
class RateLimits:
    login_per_ip: Limit
    login_failures_per_account: Limit
    requests_per_user: Limit
    writes_per_user: Limit

    @classmethod
    def from_settings(cls, settings: Settings) -> "RateLimits":
        return cls(
            login_per_ip=Limit(settings.rate_login_per_ip_per_minute, 60),
            login_failures_per_account=Limit(settings.rate_login_failures_per_account, 15 * 60),
            requests_per_user=Limit(settings.rate_requests_per_user_per_minute, 60),
            writes_per_user=Limit(settings.rate_writes_per_user_per_minute, 60),
        )


class RequestLimits:
    """The app's limiter and policy, or a no-op when ``RATE_LIMITS_ENABLED=false``."""

    def __init__(self, settings: Settings, limiter: RateLimiter | None = None) -> None:
        self.enabled = settings.rate_limits_enabled
        self.limiter = limiter or RateLimiter()
        self.limits = RateLimits.from_settings(settings)

    def login_attempt(self, client_ip: str, email: str) -> str:
        """Count the attempt against the client; refuse if the account is locked out.

        Returns the account key, for ``login_failed`` / ``login_succeeded``.
        """
        account = f"login-account:{opaque(email)}"
        if self.enabled:
            self.limiter.hit(f"login-ip:{client_ip}", self.limits.login_per_ip)
            self.limiter.check(account, self.limits.login_failures_per_account)
        return account

    def login_failed(self, account: str) -> None:
        if self.enabled:
            self.limiter.hit(account, self.limits.login_failures_per_account)

    def login_succeeded(self, account: str) -> None:
        self.limiter.reset(account)

    def request(self, user_id: uuid.UUID) -> None:
        if self.enabled:
            self.limiter.hit(f"user:{user_id}", self.limits.requests_per_user)

    def write(self, user_id: uuid.UUID) -> None:
        if self.enabled:
            self.limiter.hit(f"write:{user_id}", self.limits.writes_per_user)


def get_request_limits(request: Request) -> RequestLimits:
    limits: RequestLimits = request.app.state.request_limits
    return limits


def client_ip(request: Request) -> str:
    """The TCP peer. ``X-Forwarded-For`` is not trusted: no proxy is configured in front."""
    return request.client.host if request.client is not None else "unknown"
