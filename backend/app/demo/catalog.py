# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""The synthetic demo world, as data.

Everything here is invented for this project: clinic names, dentists, callers, contact values
(RFC 2606 example domains, 555-01xx numbers) and every word the scripted callers say. No real
person, practice or recording is represented.

Each scenario's caller speaks an ordered list of clips. The transcript is the source text for the
synthetic audio fixtures (Milestone 5) and for the scripted mock speech-to-text provider. Clips
answer the *topic* of a step, so a live receptionist that asks in a slightly different order still
receives sensible answers (architecture risk R3).

Relative dates ("next Tuesday") are resolved against the call date in the clinic's timezone, so
scenarios never go stale. Expected values use ``next:<weekday>`` for that reason.
"""

from dataclasses import dataclass, field
from datetime import time

from app.domain.enums import ContactChannel, ConversationState, IntakeField, PatientType

S = ConversationState
F = IntakeField

HAPPY_PATH: tuple[ConversationState, ...] = (
    S.CREATED,
    S.GREETING,
    S.INTRODUCTION,
    S.IDENTITY_COLLECTION,
    S.CONTACT_DETAILS,
    S.VISIT_REASON,
    S.APPOINTMENT_PREFERENCES,
    S.INFORMATION_REVIEW,
    S.CONFIRMATION_PENDING,
    S.COMPLETED,
)


@dataclass(frozen=True)
class Clip:
    id: str
    transcript: str


@dataclass(frozen=True)
class Persona:
    key: str
    first_name: str
    last_name: str
    email: str | None
    phone: str | None
    preferred_contact_channel: ContactChannel
    patient_type: PatientType
    background: str
    # Returning patients already have a record in the clinic.
    existing_patient: bool = False


@dataclass(frozen=True)
class Scenario:
    code: str
    title: str
    objective: str
    persona_key: str
    clips: tuple[Clip, ...]
    states: tuple[ConversationState, ...]
    fields: dict[IntakeField, str]
    missing_fields: tuple[IntakeField, ...] = ()
    corrected_fields: tuple[IntakeField, ...] = ()
    escalation_reason: str | None = None

    @property
    def final_state(self) -> ConversationState:
        return self.states[-1]


@dataclass(frozen=True)
class Window:
    weekday: int  # Monday = 0
    start: time
    end: time


@dataclass(frozen=True)
class Dentist:
    display_name: str
    hours: tuple[Window, ...]


@dataclass(frozen=True)
class AppointmentType:
    code: str
    name: str
    duration_minutes: int


@dataclass(frozen=True)
class Clinic:
    slug: str
    name: str
    timezone: str
    dentists: tuple[Dentist, ...]
    appointment_types: tuple[AppointmentType, ...]
    personas: tuple[Persona, ...]
    scenarios: tuple[Scenario, ...] = field(default=())


def _weekdays(*spans: tuple[time, time], days: range = range(5)) -> tuple[Window, ...]:
    return tuple(Window(day, start, end) for day in days for start, end in spans)


_SPLIT_DAY = ((time(9, 0), time(12, 30)), (time(13, 30), time(17, 0)))

_APPOINTMENT_TYPES = (
    AppointmentType("hygiene_cleaning", "Hygiene cleaning", 45),
    AppointmentType("checkup", "Routine check-up", 30),
    AppointmentType("new_patient_exam", "New patient examination", 60),
    AppointmentType("follow_up", "Follow-up visit", 30),
)

BRIGHTSMILE = Clinic(
    slug="brightsmile",
    name="BrightSmile Dental Studio",
    timezone="Europe/London",
    dentists=(
        Dentist("Dr. Mira Calloway", _weekdays(*_SPLIT_DAY)),
        Dentist(
            "Dr. Tomas Reyland",
            (
                *_weekdays(*_SPLIT_DAY, days=range(1, 5)),
                Window(5, time(9, 0), time(13, 0)),  # Saturday mornings
            ),
        ),
    ),
    appointment_types=_APPOINTMENT_TYPES,
    personas=(
        Persona(
            key="ava",
            first_name="Ava",
            last_name="Lindqvist",
            email="ava.lindqvist@example.com",
            phone="+1-555-0101",
            preferred_contact_channel=ContactChannel.EMAIL,
            patient_type=PatientType.NEW,
            background="New to the area and looking for a routine cleaning.",
        ),
        Persona(
            key="marcus",
            first_name="Marcus",
            last_name="Bellweather",
            email="marcus.b@example.org",
            phone="+1-555-0102",
            preferred_contact_channel=ContactChannel.PHONE,
            patient_type=PatientType.RETURNING,
            background="Existing patient booking the follow-up his dentist recommended.",
            existing_patient=True,
        ),
        Persona(
            key="elena",
            first_name="Elena",
            last_name="Fairbanks",
            email="elena.fairbanks@example.net",
            phone="+1-555-0103",
            preferred_contact_channel=ContactChannel.EMAIL,
            patient_type=PatientType.NEW,
            background="Changes her mind about the day and corrects a misheard email address.",
        ),
        Persona(
            key="jordan",
            first_name="Jordan",
            last_name="Okonkwo-Hale",
            email=None,
            phone="+1-555-0104",
            preferred_contact_channel=ContactChannel.PHONE,
            patient_type=PatientType.NEW,
            background="Calls between meetings and cannot commit to a date or time.",
        ),
        Persona(
            key="noah",
            first_name="Noah",
            last_name="Brightwater",
            email="noah.brightwater@example.com",
            phone="+1-555-0105",
            preferred_contact_channel=ContactChannel.PHONE,
            patient_type=PatientType.RETURNING,
            background="Describes symptoms that the demo protocol treats as urgent.",
            existing_patient=True,
        ),
    ),
    scenarios=(
        Scenario(
            code="A",
            title="New patient: routine cleaning",
            objective="Register a new patient and capture a cleaning request and preferred slot.",
            persona_key="ava",
            clips=(
                Clip("a-01", "Hi! I'd like to book a teeth cleaning, please. I'm a new patient."),
                Clip("a-02", "Sure. My name is Ava Lindqvist."),
                Clip("a-03", "Email is best. It's ava dot lindqvist at example dot com."),
                Clip("a-04", "And my phone number is 555-0101."),
                Clip("a-05", "Just a routine cleaning. Nothing is hurting."),
                Clip("a-06", "Next Tuesday would be great, around ten in the morning."),
                Clip("a-07", "Yes, that all sounds correct."),
                Clip("a-08", "Yes, please go ahead and confirm it."),
            ),
            states=HAPPY_PATH,
            fields={
                F.FIRST_NAME: "Ava",
                F.LAST_NAME: "Lindqvist",
                F.PATIENT_TYPE: "new",
                F.PREFERRED_CONTACT_CHANNEL: "email",
                F.EMAIL: "ava.lindqvist@example.com",
                F.PHONE: "+1-555-0101",
                F.VISIT_REASON: "routine cleaning",
                F.REQUESTED_SERVICE: "hygiene_cleaning",
                F.PREFERRED_DATE: "next:tuesday",
                F.PREFERRED_TIME: "10:00",
            },
        ),
        Scenario(
            code="B",
            title="Returning patient: follow-up",
            objective="Recognise an existing patient by contact value and book a follow-up visit.",
            persona_key="marcus",
            clips=(
                Clip("b-01", "Hello, I'm an existing patient. I need to book a follow-up visit."),
                Clip("b-02", "It's Marcus Bellweather."),
                Clip("b-03", "A phone call is best. My number is 555-0102."),
                Clip("b-04", "My email is marcus dot b at example dot org."),
                Clip("b-05", "Dr. Calloway asked me to come back to check on a filling."),
                Clip("b-06", "Thursday next week, in the afternoon. Maybe two o'clock?"),
                Clip("b-07", "Yes, that's right."),
                Clip("b-08", "Yes, confirm it please."),
            ),
            states=HAPPY_PATH,
            fields={
                F.FIRST_NAME: "Marcus",
                F.LAST_NAME: "Bellweather",
                F.PATIENT_TYPE: "returning",
                F.PREFERRED_CONTACT_CHANNEL: "phone",
                F.EMAIL: "marcus.b@example.org",
                F.PHONE: "+1-555-0102",
                F.VISIT_REASON: "check on a filling",
                F.REQUESTED_SERVICE: "follow_up",
                F.PREFERRED_DATE: "next:thursday",
                F.PREFERRED_TIME: "14:00",
            },
        ),
        Scenario(
            code="C",
            title="Caller corrects a date and an email address",
            objective="Apply corrections to previously captured values and keep their history.",
            persona_key="elena",
            clips=(
                Clip("c-01", "Hi, I'm a new patient and I'd like a check-up."),
                Clip("c-02", "My name is Elena Fairbanks."),
                Clip("c-03", "Please email me at elena dot fairbank at example dot net."),
                Clip("c-04", "Sorry, I missed a letter. It's fairbanks with an s at the end."),
                Clip("c-05", "My phone is 555-0103."),
                Clip("c-06", "A regular check-up. It's been about a year."),
                Clip("c-07", "Next Monday at nine thirty, please."),
                Clip("c-08", "Actually, can we make that next Wednesday instead? Same time."),
                Clip("c-09", "Yes, everything is correct now."),
                Clip("c-10", "Yes, please confirm."),
            ),
            states=(
                S.CREATED,
                S.GREETING,
                S.INTRODUCTION,
                S.IDENTITY_COLLECTION,
                S.CONTACT_DETAILS,
                S.VISIT_REASON,
                S.APPOINTMENT_PREFERENCES,
                S.INFORMATION_REVIEW,
                S.APPOINTMENT_PREFERENCES,
                S.INFORMATION_REVIEW,
                S.CONFIRMATION_PENDING,
                S.COMPLETED,
            ),
            fields={
                F.FIRST_NAME: "Elena",
                F.LAST_NAME: "Fairbanks",
                F.PATIENT_TYPE: "new",
                F.PREFERRED_CONTACT_CHANNEL: "email",
                F.EMAIL: "elena.fairbanks@example.net",
                F.PHONE: "+1-555-0103",
                F.VISIT_REASON: "regular check-up",
                F.REQUESTED_SERVICE: "checkup",
                F.PREFERRED_DATE: "next:wednesday",
                F.PREFERRED_TIME: "09:30",
            },
            corrected_fields=(F.EMAIL, F.PREFERRED_DATE),
        ),
        Scenario(
            code="D",
            title="Incomplete information",
            objective=(
                "Ask for missing details without guessing them, and end the call honestly when "
                "the caller cannot provide them."
            ),
            persona_key="jordan",
            clips=(
                Clip("d-01", "Hi, um, I think I need to see a dentist. I haven't been before."),
                Clip("d-02", "Jordan Okonkwo-Hale."),
                Clip("d-03", "Just call me. 555-0104."),
                Clip("d-04", "I'd rather not do email."),
                Clip("d-05", "A check-up, I guess. It's been a while."),
                Clip("d-06", "I'm not sure when I'm free, I'll have to look at my calendar."),
                Clip("d-07", "I really don't know yet. I'll call back another time. Bye."),
            ),
            states=(
                S.CREATED,
                S.GREETING,
                S.INTRODUCTION,
                S.IDENTITY_COLLECTION,
                S.CONTACT_DETAILS,
                S.VISIT_REASON,
                S.APPOINTMENT_PREFERENCES,
                S.ABANDONED,
            ),
            fields={
                F.FIRST_NAME: "Jordan",
                F.LAST_NAME: "Okonkwo-Hale",
                F.PATIENT_TYPE: "new",
                F.PREFERRED_CONTACT_CHANNEL: "phone",
                F.PHONE: "+1-555-0104",
                F.VISIT_REASON: "check-up",
                F.REQUESTED_SERVICE: "checkup",
            },
            missing_fields=(F.EMAIL, F.PREFERRED_DATE, F.PREFERRED_TIME),
        ),
        Scenario(
            code="E",
            title="Urgent symptoms: escalation",
            objective=(
                "Recognise symptoms the demo protocol classes as urgent, stop routine intake and "
                "escalate. No clinical advice is given."
            ),
            persona_key="noah",
            clips=(
                Clip(
                    "e-01",
                    "Hi, I'm a patient there. My jaw is really swollen, I have a fever, and it's "
                    "getting hard to swallow.",
                ),
                Clip("e-02", "Okay. Thank you."),
            ),
            states=(S.CREATED, S.GREETING, S.INTRODUCTION, S.ESCALATED),
            fields={F.PATIENT_TYPE: "returning"},
            escalation_reason="urgent_symptoms",
        ),
    ),
)

JUNIPER_VALE = Clinic(
    slug="juniper-vale",
    name="Juniper & Vale Dental",
    timezone="America/New_York",
    dentists=(
        Dentist(
            "Dr. Anika Rourke", _weekdays((time(8, 0), time(12, 0)), (time(13, 0), time(16, 0)))
        ),
        Dentist("Dr. Samuel Whitlow", _weekdays((time(10, 0), time(18, 0)), days=range(0, 4))),
    ),
    appointment_types=_APPOINTMENT_TYPES,
    personas=(
        Persona(
            key="priya",
            first_name="Priya",
            last_name="Castellane",
            email="priya.castellane@example.org",
            phone="+1-555-0111",
            preferred_contact_channel=ContactChannel.EMAIL,
            patient_type=PatientType.NEW,
            background="Moving to the city and registering before her first cleaning.",
        ),
    ),
    scenarios=(
        Scenario(
            code="A",
            title="New patient: routine cleaning",
            objective="Register a new patient and capture a cleaning request and preferred slot.",
            persona_key="priya",
            clips=(
                Clip("ja-01", "Hello! I'm new and I'd like to schedule a cleaning."),
                Clip("ja-02", "Priya Castellane."),
                Clip("ja-03", "Email please: priya dot castellane at example dot org."),
                Clip("ja-04", "My phone number is 555-0111."),
                Clip("ja-05", "Just a cleaning."),
                Clip("ja-06", "Next Friday, in the morning. Around nine?"),
                Clip("ja-07", "Yes, correct."),
                Clip("ja-08", "Yes, please book it."),
            ),
            states=HAPPY_PATH,
            fields={
                F.FIRST_NAME: "Priya",
                F.LAST_NAME: "Castellane",
                F.PATIENT_TYPE: "new",
                F.PREFERRED_CONTACT_CHANNEL: "email",
                F.EMAIL: "priya.castellane@example.org",
                F.PHONE: "+1-555-0111",
                F.VISIT_REASON: "cleaning",
                F.REQUESTED_SERVICE: "hygiene_cleaning",
                F.PREFERRED_DATE: "next:friday",
                F.PREFERRED_TIME: "09:00",
            },
        ),
    ),
)

CLINICS: tuple[Clinic, ...] = (BRIGHTSMILE, JUNIPER_VALE)


def clip_index() -> dict[str, Clip]:
    """Every clip by ID. Clip IDs are globally unique (they name fixture files)."""
    index: dict[str, Clip] = {}
    for clinic in CLINICS:
        for scenario in clinic.scenarios:
            for clip in scenario.clips:
                if clip.id in index:
                    raise ValueError(f"Duplicate clip id {clip.id!r}")
                index[clip.id] = clip
    return index
