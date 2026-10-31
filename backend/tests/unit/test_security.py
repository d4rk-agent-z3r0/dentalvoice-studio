# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from pydantic import SecretStr, ValidationError

from app.core.security import (
    ALGORITHM,
    AUDIENCE,
    ISSUER,
    AuthError,
    Principal,
    decode_access_token,
    issue_access_token,
)
from app.domain.enums import ClinicRole
from tests.conftest import TEST_JWT_SECRET, UNREACHABLE_DATABASE_URL, make_test_settings

SETTINGS = make_test_settings(UNREACHABLE_DATABASE_URL)
PRINCIPAL = Principal(uuid.uuid4(), uuid.uuid4(), ClinicRole.STAFF)


def test_round_trip_preserves_identity_clinic_and_role() -> None:
    assert decode_access_token(SETTINGS, issue_access_token(SETTINGS, PRINCIPAL)) == PRINCIPAL


def test_expired_token_is_rejected() -> None:
    token = issue_access_token(SETTINGS, PRINCIPAL, now=datetime.now(UTC) - timedelta(days=1))
    with pytest.raises(AuthError, match="expired"):
        decode_access_token(SETTINGS, token)


def test_token_signed_with_another_key_is_rejected() -> None:
    other = make_test_settings(UNREACHABLE_DATABASE_URL, jwt_secret=SecretStr("x" * 40))
    with pytest.raises(AuthError):
        decode_access_token(SETTINGS, issue_access_token(other, PRINCIPAL))


def test_unsigned_token_is_rejected() -> None:
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": str(PRINCIPAL.user_id),
        "clinic_id": str(PRINCIPAL.clinic_id),
        "role": "admin",
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(hours=1),
    }
    forged = jwt.encode(claims, key="", algorithm="none")
    with pytest.raises(AuthError):
        decode_access_token(SETTINGS, forged)


@pytest.mark.parametrize("missing", ["exp", "sub", "aud", "iss", "clinic_id", "role"])
def test_tokens_missing_a_claim_are_rejected(missing: str) -> None:
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": str(PRINCIPAL.user_id),
        "clinic_id": str(PRINCIPAL.clinic_id),
        "role": "staff",
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(hours=1),
    }
    del claims[missing]
    token = jwt.encode(claims, TEST_JWT_SECRET, algorithm=ALGORITHM)
    with pytest.raises(AuthError):
        decode_access_token(SETTINGS, token)


def test_short_signing_keys_are_refused() -> None:
    with pytest.raises(ValidationError, match="at least 32"):
        make_test_settings(UNREACHABLE_DATABASE_URL, jwt_secret=SecretStr("short"))


def test_missing_key_is_a_configuration_error() -> None:
    unset = make_test_settings(UNREACHABLE_DATABASE_URL, jwt_secret=None)
    with pytest.raises(AuthError) as caught:
        issue_access_token(unset, PRINCIPAL)
    assert caught.value.code == "AUTH_NOT_CONFIGURED"
