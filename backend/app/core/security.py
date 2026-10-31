# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Access tokens. The active clinic is a signed claim: the only place a clinic id comes from."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import Settings
from app.domain.enums import ClinicRole

ALGORITHM = "HS256"
ISSUER = "dentalvoice-studio"
AUDIENCE = "dentalvoice-api"


class AuthError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    clinic_id: uuid.UUID
    role: ClinicRole


def _secret(settings: Settings) -> str:
    if settings.jwt_secret is None:
        raise AuthError("AUTH_NOT_CONFIGURED", "Authentication is not configured (JWT_SECRET).")
    return settings.jwt_secret.get_secret_value()


def issue_access_token(
    settings: Settings, principal: Principal, *, now: datetime | None = None
) -> str:
    issued = now or datetime.now(UTC)
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": str(principal.user_id),
        "clinic_id": str(principal.clinic_id),
        "role": principal.role.value,
        "iat": issued,
        "exp": issued + timedelta(minutes=settings.jwt_ttl_minutes),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, _secret(settings), algorithm=ALGORITHM)


def decode_access_token(settings: Settings, token: str) -> Principal:
    try:
        claims = jwt.decode(
            token,
            _secret(settings),
            algorithms=[ALGORITHM],  # fixed list: "none" and algorithm confusion are impossible
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
        return Principal(
            user_id=uuid.UUID(claims["sub"]),
            clinic_id=uuid.UUID(claims["clinic_id"]),
            role=ClinicRole(claims["role"]),
        )
    except jwt.ExpiredSignatureError as error:
        raise AuthError("AUTH_INVALID", "The access token has expired.") from error
    except (jwt.InvalidTokenError, KeyError, ValueError) as error:
        raise AuthError("AUTH_INVALID", "The access token is invalid.") from error
