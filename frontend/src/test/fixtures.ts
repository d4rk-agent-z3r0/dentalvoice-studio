// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
/** Synthetic fixtures shaped like real API responses (captured from the M3 backend). */
import type {
  Conversation,
  ConversationDetail,
  IntakeDraft,
  Scenario,
  TurnResult,
} from "@/lib/api/types";

export const CLINIC_ID = "01a191cc-3a00-7000-8000-00000000c11c";
export const SCENARIO_ID = "01a191cc-3a27-71ac-84ab-ca4599adaa3a";
export const CONVERSATION_ID = "01a191cc-ade4-7197-9e80-ad9477bbf4f2";

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
