# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""The synthetic catalogue is data, so it gets the same scrutiny as code."""

import re
from datetime import UTC, date, datetime, time

import pytest

from app.demo import catalog
from app.demo.seed import expectation
from app.domain.contact import normalise_email, normalise_phone
from app.domain.enums import ConversationState, IntakeField
from app.services.calendar import WeeklyWindow, slot_bounds

SCENARIOS = [(clinic, scenario) for clinic in catalog.CLINICS for scenario in clinic.scenarios]
IDS = [f"{clinic.slug}-{scenario.code}" for clinic, scenario in SCENARIOS]


def test_primary_clinic_has_the_five_required_scenarios() -> None:
    assert [s.code for s in catalog.BRIGHTSMILE.scenarios] == ["A", "B", "C", "D", "E"]


def test_clip_ids_are_globally_unique_and_file_safe() -> None:
    index = catalog.clip_index()
    assert all(re.fullmatch(r"[a-z]{1,2}-\d{2}", clip_id) for clip_id in index)


def test_clinic_slugs_and_scenario_codes_are_unique() -> None:
    assert len({c.slug for c in catalog.CLINICS}) == len(catalog.CLINICS)
    for clinic in catalog.CLINICS:
        codes = [s.code for s in clinic.scenarios]
        assert len(codes) == len(set(codes))


@pytest.mark.parametrize("persona", [p for c in catalog.CLINICS for p in c.personas])
def test_persona_contact_values_are_reserved_and_canonical(persona: catalog.Persona) -> None:
    if persona.email is not None:
        assert normalise_email(persona.email) == persona.email
    if persona.phone is not None:
        assert normalise_phone(persona.phone) == persona.phone


@pytest.mark.parametrize(("clinic", "scenario"), SCENARIOS, ids=IDS)
def test_scenario_is_internally_consistent(
    clinic: catalog.Clinic, scenario: catalog.Scenario
) -> None:
    personas = {p.key: p for p in clinic.personas}
    persona = personas[scenario.persona_key]
    service_codes = {t.code for t in clinic.appointment_types}

    assert scenario.states[0] is ConversationState.CREATED
    assert scenario.clips, "every scenario needs at least one caller clip"
    if IntakeField.REQUESTED_SERVICE in scenario.fields:
        assert scenario.fields[IntakeField.REQUESTED_SERVICE] in service_codes
    for contact_field, value in (
        (IntakeField.EMAIL, persona.email),
        (IntakeField.PHONE, persona.phone),
        (IntakeField.FIRST_NAME, persona.first_name),
        (IntakeField.LAST_NAME, persona.last_name),
    ):
        if contact_field in scenario.fields:
            assert scenario.fields[contact_field] == value
    assert not set(scenario.missing_fields) & set(scenario.fields)
    assert set(scenario.corrected_fields) <= set(scenario.fields)
    assert (scenario.final_state is ConversationState.ESCALATED) == (
        scenario.escalation_reason is not None
    )
    expectation(scenario)  # validates against the stored schema


def test_no_routable_contact_value_appears_anywhere_in_the_catalogue() -> None:
    text = repr(catalog.CLINICS)
    emails = re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text)
    assert emails
    assert all(e.split("@")[1] in {"example.com", "example.org", "example.net"} for e in emails)
    for spoken_number in re.findall(r"\b\d{3}-\d{4}\b", text):
        assert re.fullmatch(r"555-01\d\d", spoken_number)


def test_slots_follow_local_hours_across_a_daylight_saving_change() -> None:
    # Europe/London moves from GMT to BST on Sunday 2026-03-29.
    windows = [WeeklyWindow(day, time(9, 0), time(9, 30)) for day in range(7)]
    bounds = list(slot_bounds(windows, "Europe/London", date(2026, 3, 28), 2))

    assert [start for start, _ in bounds] == [
        datetime(2026, 3, 28, 9, 0, tzinfo=UTC),
        datetime(2026, 3, 28, 9, 15, tzinfo=UTC),
        datetime(2026, 3, 29, 8, 0, tzinfo=UTC),  # still 09:00 on the clinic's wall clock
        datetime(2026, 3, 29, 8, 15, tzinfo=UTC),
    ]


def test_slots_only_cover_whole_blocks_inside_each_window() -> None:
    windows = [
        WeeklyWindow(0, time(9, 0), time(12, 30)),
        WeeklyWindow(0, time(13, 30), time(13, 50)),
    ]
    bounds = list(slot_bounds(windows, "UTC", date(2026, 11, 2), 7))  # Monday + six other days
    assert len(bounds) == 14 + 1  # 3.5 h of 15-minute blocks, then one whole block before 13:50
    assert all((end - start).total_seconds() == 900 for start, end in bounds)
