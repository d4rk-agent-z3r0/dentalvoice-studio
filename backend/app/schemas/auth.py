# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Sign-in and session shapes (docs/api-reference.md, "Auth")."""

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.passwords import MAX_LENGTH
from app.domain.enums import ClinicRole


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    email: str = Field(min_length=3, max_length=254)
    # Not validated against the password policy here: a sign-in attempt only needs to be bounded.
    password: str = Field(min_length=1, max_length=MAX_LENGTH, repr=False)


class SwitchClinicRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    clinic_id: uuid.UUID


class UserRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    email: str
    display_name: str


class SessionClinic(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    name: str
    timezone: str


class Membership(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    name: str
    role: ClinicRole


class MeRead(BaseModel):
    """Who the token belongs to, read from the database (not from the token)."""

    model_config = ConfigDict(frozen=True)

    user: UserRead
    clinic: SessionClinic
    role: ClinicRole
    clinics: list[Membership]  # every clinic this user belongs to, by name


class SessionRead(MeRead):
    access_token: str = Field(repr=False)
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - the scheme name, not a secret
    expires_in: int  # seconds
