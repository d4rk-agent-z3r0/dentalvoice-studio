# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Structural guard: every repository read or write is scoped by an explicit ``clinic_id``."""

import inspect

import pytest

from app.repositories.analytics import AnalyticsRepository
from app.repositories.appointments import AppointmentRepository
from app.repositories.clinics import ClinicRepository
from app.repositories.conversations import ConversationRepository
from app.repositories.dentists import AppointmentTypeRepository, DentistRepository
from app.repositories.intake import EventRepository, IntakeRepository
from app.repositories.patients import PatientRepository
from app.repositories.scenarios import ScenarioRepository
from app.repositories.slots import SlotRepository
from app.repositories.turns import TurnRepository

REPOSITORIES = [
    AnalyticsRepository,
    AppointmentRepository,
    AppointmentTypeRepository,
    ClinicRepository,
    ConversationRepository,
    DentistRepository,
    EventRepository,
    IntakeRepository,
    PatientRepository,
    ScenarioRepository,
    SlotRepository,
    TurnRepository,
]
# These receive an ORM object whose clinic_id the caller has already set.
UNSCOPED_ALLOWED = {"add", "add_snapshot"}


def _public_methods(cls: type) -> list[str]:
    return [
        name
        for name, member in inspect.getmembers(cls, inspect.isfunction)
        if not name.startswith("_") and name not in UNSCOPED_ALLOWED
    ]


@pytest.mark.parametrize("repository", REPOSITORIES, ids=lambda cls: cls.__name__)
def test_every_query_takes_clinic_id_first(repository: type) -> None:
    methods = _public_methods(repository)
    assert methods
    for name in methods:
        params = list(inspect.signature(getattr(repository, name)).parameters)
        assert params[:2] == ["self", "clinic_id"], f"{repository.__name__}.{name}"
