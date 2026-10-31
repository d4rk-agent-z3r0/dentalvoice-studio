# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Shared schema building blocks."""

from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints

from app.domain.contact import normalise_email, normalise_phone


class ReadModel(BaseModel):
    """Response DTO built from an ORM row."""

    model_config = ConfigDict(from_attributes=True, frozen=True)


class WriteModel(BaseModel):
    """Request DTO: unknown fields are an error, never silently dropped."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


PersonName = Annotated[str, StringConstraints(min_length=1, max_length=80)]
ReservedEmail = Annotated[str, AfterValidator(normalise_email)]
ReservedPhone = Annotated[str, AfterValidator(normalise_phone)]
