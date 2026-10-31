// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
/**
 * Response and request shapes of the DentalVoice API, mirroring the backend Pydantic schemas in
 * `backend/app/schemas/` and the vocabularies in `backend/app/domain/enums.py`. Keep in sync by hand
 * until an OpenAPI generator is justified.
 */

export const CONVERSATION_STATES = [
  "CREATED",
  "GREETING",
  "INTRODUCTION",
  "IDENTITY_COLLECTION",
  "CONTACT_DETAILS",
  "VISIT_REASON",
  "APPOINTMENT_PREFERENCES",
  "INFORMATION_REVIEW",
  "CONFIRMATION_PENDING",
  "COMPLETED",
  "ESCALATED",
  "ABANDONED",
] as const;
export type ConversationState = (typeof CONVERSATION_STATES)[number];

export const TERMINAL_STATES: ReadonlySet<ConversationState> = new Set<ConversationState>([
  "COMPLETED",
  "ESCALATED",
  "ABANDONED",
]);

export function isConversationState(value: string): value is ConversationState {
  return (CONVERSATION_STATES as readonly string[]).includes(value);
}

export type ClinicRole = "admin" | "staff" | "viewer";
export type Speaker = "caller" | "receptionist";
export type ProviderMode = "mock" | "live";
export type PatientType = "new" | "returning";
export type ContactChannel = "email" | "phone";

export const INTAKE_FIELDS = [
  "first_name",
  "last_name",
  "patient_type",
  "preferred_contact_channel",
  "email",
  "phone",
  "visit_reason",
  "requested_service",
  "preferred_date",
  "preferred_time",
] as const;
export type IntakeField = (typeof INTAKE_FIELDS)[number];

export type IntakeFieldStatus =
  | "provided"
  | "not_provided"
  | "needs_confirmation"
  | "confirmed"
  | "rejected"
  | "superseded";

/** `ScenarioRead`. */
export interface Scenario {
  id: string;
  code: string;
  title: string;
  objective: string;
  clips: string[];
  persona_id: string;
}

/** `ConversationRead`. Timestamps are ISO 8601 strings in UTC. */
export interface Conversation {
  id: string;
  scenario_id: string;
  patient_id: string | null;
  state: ConversationState;
  state_version: number;
  provider_mode: ProviderMode;
  turn_count: number;
  started_at: string | null;
  ended_at: string | null;
  created_at: string;
}

/** `TurnRead`. Latencies are measured server-side; `null` means not measured. */
export interface Turn {
  seq: number;
  speaker: Speaker;
  text: string;
  clip_id: string | null;
  stt_ms: number | null;
  llm_ms: number | null;
  tts_ms: number | null;
  total_ms: number | null;
  created_at: string;
}

/** `EventRead`. The payload shape depends on `type`. */
export interface ConversationEvent {
  type: string;
  payload: Record<string, unknown>;
  created_at: string;
}

/** `IntakeDraftRead`. `confidence` is a decimal serialised as a string (e.g. `"0.950"`). */
export interface IntakeDraft {
  id: string;
  field: IntakeField;
  value: string | null;
  status: IntakeFieldStatus;
  confidence: string | null;
  source_turn_id: string | null;
  rejection_reason: string | null;
  created_at: string;
}

/** `IntakeSnapshotData`: the confirmed result of a completed call. */
export interface IntakeSnapshot {
  first_name: string;
  last_name: string;
  patient_type: PatientType;
  preferred_contact_channel: ContactChannel;
  email: string | null;
  phone: string | null;
  visit_reason: string;
  requested_service: string;
  /** `YYYY-MM-DD` in the clinic's calendar. */
  preferred_date: string;
  /** `HH:MM:SS` clinic-local time. */
  preferred_time: string;
  provenance: Partial<Record<IntakeField, string>>;
}

/** `ConversationDetail`. */
export interface ConversationDetail {
  conversation: Conversation;
  turns: Turn[];
  events: ConversationEvent[];
  intake: IntakeDraft[];
  missing_fields: IntakeField[];
  snapshot: IntakeSnapshot | null;
}

/** `TurnResultRead`: the outcome of `/start` and `/turns`. */
export interface TurnResult {
  conversation_id: string;
  previous_state: ConversationState;
  state: ConversationState;
  path: ConversationState[];
  state_version: number;
  reply: string;
  receptionist_turn_seq: number;
  caller_turn_seq: number | null;
  missing_fields: IntakeField[];
  rejected_fields: Partial<Record<IntakeField, string>>;
  corrected_fields: IntakeField[];
  llm_ms: number | null;
}

export interface ListConversationsParams {
  state?: ConversationState;
  /** 1–100; the backend default is 50. */
  limit?: number;
}
