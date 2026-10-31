// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
/** Synthetic fixtures shaped like real API responses (captured from the M3 backend). */
import type {
  AuthMe,
  AuthTokenResponse,
  Appointment,
  Availability,
  ClinicInfo,
  Conversation,
  ConversationDetail,
  IntakeDraft,
  Patient,
  PatientDetail,
  Scenario,
  TurnResult,
} from "@/lib/api/types";

export const CLINIC_ID = "01a191cc-3a00-7000-8000-00000000c11c";
export const SCENARIO_ID = "01a191cc-3a27-71ac-84ab-ca4599adaa3a";
export const CONVERSATION_ID = "01a191cc-ade4-7197-9e80-ad9477bbf4f2";
export const PATIENT_ID = "01a191cd-0b1e-7c3a-9a51-5a7d1e000001";
export const APPOINTMENT_ID = "01a191cd-4c2f-7d01-8b11-a9f0e0000a01";
export const DENTIST_ID = "01a191cc-3a10-7000-8000-00000000d001";
export const CHECKUP_TYPE_ID = "01a191cc-3a20-7000-8000-00000000a001";

export const CLEANING_TYPE_ID = "01a191cc-3a20-7000-8000-00000000a002";
export const SECOND_DENTIST_ID = "01a191cc-3a10-7000-8000-00000000d002";

export function clinicInfo(overrides: Partial<ClinicInfo> = {}): ClinicInfo {
  return {
    id: CLINIC_ID,
    name: "BrightSmile Dental Studio",
    timezone: "Europe/London",
    today: "2026-11-02",
    appointment_types: [
      { id: CHECKUP_TYPE_ID, code: "checkup", name: "Check-up", duration_minutes: 30, is_active: true },
      {
        id: CLEANING_TYPE_ID,
        code: "hygiene_cleaning",
        name: "Hygiene cleaning",
        duration_minutes: 45,
        is_active: true,
      },
    ],
    dentists: [
      { id: DENTIST_ID, display_name: "Dr. Ada Example", is_active: true },
      { id: SECOND_DENTIST_ID, display_name: "Dr. Bo Example", is_active: true },
    ],
    ...overrides,
  };
}

export function availability(
  slots: Array<{ start: string; end: string; dentist?: "ada" | "bo" }>,
  overrides: Partial<Availability> = {},
): Availability {
  return {
    appointment_type_id: CHECKUP_TYPE_ID,
    duration_minutes: 30,
    timezone: "Europe/London",
    first_day: "2026-11-02",
    days: 1,
    slots: slots.map(({ start, end, dentist = "ada" }) => ({
      dentist_id: dentist === "ada" ? DENTIST_ID : SECOND_DENTIST_ID,
      dentist_name: dentist === "ada" ? "Dr. Ada Example" : "Dr. Bo Example",
      starts_at: `2026-11-02T${start}:00Z`,
      ends_at: `2026-11-02T${end}:00Z`,
      starts_at_local: `2026-11-02T${start}:00+00:00`,
      ends_at_local: `2026-11-02T${end}:00+00:00`,
    })),
    ...overrides,
  };
}

export function patient(overrides: Partial<Patient> = {}): Patient {
  return {
    id: PATIENT_ID,
    first_name: "Ava",
    last_name: "Lindqvist",
    email: "ava.lindqvist@example.com",
    phone: "+1-555-0101",
    preferred_contact_channel: "email",
    patient_type: "new",
    status: "registered",
    created_at: "2026-10-31T12:03:10.512000Z",
    updated_at: "2026-10-31T12:03:10.512000Z",
    ...overrides,
  };
}

export function appointment(overrides: Partial<Appointment> = {}): Appointment {
  return {
    id: APPOINTMENT_ID,
    patient_id: PATIENT_ID,
    dentist_id: DENTIST_ID,
    appointment_type_id: CHECKUP_TYPE_ID,
    conversation_id: null,
    rescheduled_from_id: null,
    status: "confirmed",
    starts_at: "2026-11-03T10:00:00Z",
    ends_at: "2026-11-03T10:30:00Z",
    starts_at_local: "2026-11-03T10:00:00+00:00",
    ends_at_local: "2026-11-03T10:30:00+00:00",
    timezone: "Europe/London",
    created_at: "2026-10-31T12:10:00Z",
    updated_at: "2026-10-31T12:10:00Z",
    ...overrides,
  };
}

export function patientDetail(overrides: Partial<PatientDetail> = {}): PatientDetail {
  return {
    patient: patient(),
    conversations: [
      {
        id: CONVERSATION_ID,
        scenario_id: SCENARIO_ID,
        state: "COMPLETED",
        provider_mode: "mock",
        turn_count: 17,
        started_at: "2026-10-31T12:00:00Z",
        ended_at: "2026-10-31T12:03:10Z",
        created_at: "2026-10-31T11:59:58Z",
        snapshot_confirmed_at: "2026-10-31T12:03:10Z",
      },
    ],
    appointments: [appointment()],
    latest_snapshot: {
      conversation_id: CONVERSATION_ID,
      confirmed_at: "2026-10-31T12:03:10Z",
      patient_type: "new",
      preferred_contact_channel: "email",
      visit_reason: "Routine cleaning",
      requested_service: "hygiene_cleaning",
      preferred_date: "2026-11-03",
      preferred_time: "10:00:00",
    },
    ...overrides,
  };
}

function base64Url(value: object): string {
  return btoa(JSON.stringify(value)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** A JWT-shaped string with the backend's claims. The signature is fake: the UI never checks it. */
export function makeToken(
  claims: Partial<{ clinic_id: string; role: string; sub: string; exp: number }> = {},
): string {
  const payload = {
    iss: "dentalvoice-studio",
    aud: "dentalvoice-api",
    sub: "01a191cc-3a00-7000-8000-0000000005e7",
    clinic_id: CLINIC_ID,
    role: "staff",
    iat: 1_900_000_000,
    exp: 4_000_000_000,
    ...claims,
  };
  return `${base64Url({ alg: "HS256", typ: "JWT" })}.${base64Url(payload)}.c2lnbmF0dXJl`;
}

export const USER_ID = "01a191cc-3a00-7000-8000-0000000005e7";
export const SECOND_CLINIC_ID = "01a191cc-3a00-7000-8000-00000000c22c";

/** The demo admin's view: a member of two clinics, signed in to the first. */
export function authMe(overrides: Partial<AuthMe> = {}): AuthMe {
  return {
    user: { id: USER_ID, email: "demo.admin@example.com", display_name: "Demo Admin" },
    clinic: { id: CLINIC_ID, name: "BrightSmile Dental", timezone: "Europe/London" },
    role: "admin",
    clinics: [
      { id: CLINIC_ID, name: "BrightSmile Dental", role: "admin" },
      { id: SECOND_CLINIC_ID, name: "Harbour View Dental", role: "staff" },
    ],
    ...overrides,
  };
}

/** A login or switch-clinic response whose token carries the same clinic and role. */
export function authTokenResponse(overrides: Partial<AuthMe> = {}): AuthTokenResponse {
  const me = authMe(overrides);
  return {
    access_token: makeToken({ clinic_id: me.clinic.id, role: me.role, sub: me.user.id }),
    token_type: "bearer",
    expires_in: 3600,
    ...me,
  };
}

export function scenario(overrides: Partial<Scenario> = {}): Scenario {
  return {
    id: SCENARIO_ID,
    code: "A",
    title: "New patient: routine cleaning",
    objective: "Register a new patient and capture a cleaning request and preferred slot.",
    clips: ["a-01", "a-02"],
    persona_id: "01a191cc-3a03-7034-9952-02cf597e84a5",
    ...overrides,
  };
}

export function conversation(overrides: Partial<Conversation> = {}): Conversation {
  return {
    id: CONVERSATION_ID,
    scenario_id: SCENARIO_ID,
    patient_id: null,
    state: "CREATED",
    state_version: 1,
    provider_mode: "mock",
    turn_count: 0,
    started_at: null,
    ended_at: null,
    created_at: "2026-10-31T11:51:12.607677Z",
    ...overrides,
  };
}

export function turnResult(overrides: Partial<TurnResult> = {}): TurnResult {
  return {
    conversation_id: CONVERSATION_ID,
    previous_state: "CREATED",
    state: "GREETING",
    path: ["GREETING"],
    state_version: 2,
    reply: "Hello! Welcome to BrightSmile Dental Studio. How may I help you today?",
    receptionist_turn_seq: 1,
    caller_turn_seq: null,
    missing_fields: [],
    rejected_fields: {},
    corrected_fields: [],
    llm_ms: null,
    ...overrides,
  };
}

export function draft(overrides: Partial<IntakeDraft> = {}): IntakeDraft {
  return {
    id: `draft-${Math.random().toString(36).slice(2)}`,
    field: "first_name",
    value: "Ava",
    status: "provided",
    confidence: "0.950",
    source_turn_id: null,
    rejection_reason: null,
    created_at: "2026-10-31T11:51:13Z",
    ...overrides,
  };
}

export function detail(overrides: Partial<ConversationDetail> = {}): ConversationDetail {
  return {
    conversation: conversation({
      state: "CONTACT_DETAILS",
      turn_count: 5,
      started_at: "2026-10-31T11:51:12.636086Z",
    }),
    turns: [
      {
        seq: 1,
        speaker: "receptionist",
        text: "Hello! Welcome to BrightSmile Dental Studio.",
        clip_id: null,
        stt_ms: null,
        llm_ms: null,
        tts_ms: null,
        total_ms: null,
        created_at: "2026-10-31T11:51:12.632077Z",
      },
      {
        seq: 2,
        speaker: "caller",
        text: "Hi! I'd like to book a teeth cleaning, please.",
        clip_id: null,
        stt_ms: null,
        llm_ms: null,
        tts_ms: null,
        total_ms: null,
        created_at: "2026-10-31T11:51:12.670728Z",
      },
      {
        seq: 3,
        speaker: "receptionist",
        text: "Happy to help with that. Could I have your first and last name?",
        clip_id: null,
        stt_ms: null,
        llm_ms: 412,
        tts_ms: null,
        total_ms: null,
        created_at: "2026-10-31T11:51:12.722760Z",
      },
    ],
    events: [
      {
        type: "state_changed",
        payload: { from: "CREATED", to: "GREETING" },
        created_at: "2026-10-31T11:51:12.632077Z",
      },
      {
        type: "field_proposed",
        payload: { field: "patient_type", draft_id: "x" },
        created_at: "2026-10-31T11:51:12.722760Z",
      },
      {
        type: "state_changed",
        payload: { from: "GREETING", to: "INTRODUCTION" },
        created_at: "2026-10-31T11:51:12.722760Z",
      },
    ],
    intake: [],
    missing_fields: ["email", "phone"],
    snapshot: null,
    ...overrides,
  };
}
