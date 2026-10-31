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

/** `TicketRead`: single-use WebSocket admission (ADR-0006). */
export interface WsTicket {
  ticket: string;
  /** Seconds. */
  expires_in: number;
}

export interface ListConversationsParams {
  state?: ConversationState;
  /** 1–100; the backend default is 50. */
  limit?: number;
}

export const PATIENT_STATUSES = ["prospective", "registered", "archived"] as const;
export type PatientStatus = (typeof PATIENT_STATUSES)[number];

export function isPatientStatus(value: string): value is PatientStatus {
  return (PATIENT_STATUSES as readonly string[]).includes(value);
}

/** `PatientRead`. */
export interface Patient {
  id: string;
  first_name: string;
  last_name: string;
  email: string | null;
  phone: string | null;
  preferred_contact_channel: ContactChannel | null;
  patient_type: PatientType;
  status: PatientStatus;
  created_at: string;
  updated_at: string;
}

export interface ListPatientsParams {
  /** Case-insensitive match on first, last or full name, or email. */
  q?: string;
  status?: PatientStatus;
  /** 1–100; the backend default is 50. */
  limit?: number;
  offset?: number;
}

/** `PatientConversationRead`: a conversation linked to the patient. */
export interface PatientConversation {
  id: string;
  scenario_id: string;
  state: ConversationState;
  provider_mode: ProviderMode;
  turn_count: number;
  started_at: string | null;
  ended_at: string | null;
  created_at: string;
  /** Set when the call ended with a confirmed intake snapshot. */
  snapshot_confirmed_at: string | null;
}

/** `PatientSnapshotSummary`: what the latest confirmed intake recorded about the visit. */
export interface PatientSnapshotSummary {
  conversation_id: string;
  confirmed_at: string;
  patient_type: PatientType;
  preferred_contact_channel: ContactChannel;
  visit_reason: string;
  requested_service: string;
  /** `YYYY-MM-DD` in the clinic's calendar. */
  preferred_date: string;
  /** `HH:MM:SS` clinic-local time. */
  preferred_time: string;
}

export const APPOINTMENT_STATUSES = ["requested", "confirmed", "cancelled", "rescheduled"] as const;
export type AppointmentStatus = (typeof APPOINTMENT_STATUSES)[number];

export const ACTIVE_APPOINTMENT_STATUSES: ReadonlySet<AppointmentStatus> = new Set<AppointmentStatus>(
  ["requested", "confirmed"],
);

export function isAppointmentStatus(value: string): value is AppointmentStatus {
  return (APPOINTMENT_STATUSES as readonly string[]).includes(value);
}

/**
 * `AppointmentRead`. `starts_at`/`ends_at` are UTC instants; the `*_local` strings are the same
 * instants in the clinic's timezone with their offset (e.g. `2030-01-07T09:00:00+00:00`).
 */
export interface Appointment {
  id: string;
  patient_id: string;
  dentist_id: string;
  appointment_type_id: string;
  conversation_id: string | null;
  rescheduled_from_id: string | null;
  status: AppointmentStatus;
  starts_at: string;
  ends_at: string;
  starts_at_local: string;
  ends_at_local: string;
  timezone: string;
  created_at: string;
  updated_at: string;
}

export interface ListAppointmentsParams {
  /** First clinic-local day, `YYYY-MM-DD`, inclusive. */
  from?: string;
  /** Last clinic-local day, `YYYY-MM-DD`, inclusive. */
  to?: string;
  status?: AppointmentStatus;
  /** 1–200; the backend default is 100. */
  limit?: number;
}

/** `AppointmentCreate`. `starts_at` must carry an offset; the server stores it in UTC. */
export interface AppointmentCreate {
  patient_id: string;
  appointment_type_id: string;
  dentist_id: string;
  starts_at: string;
  conversation_id: string | null;
}

export interface AvailabilityParams {
  appointmentTypeId: string;
  /** First clinic-local day, `YYYY-MM-DD`. */
  date: string;
  /** 1–14; the backend default is 1. */
  days?: number;
}

/** `AvailableSlotRead`. */
export interface AvailableSlot {
  dentist_id: string;
  dentist_name: string;
  starts_at: string;
  ends_at: string;
  starts_at_local: string;
  ends_at_local: string;
}

/** `AvailabilityRead`. */
export interface Availability {
  appointment_type_id: string;
  duration_minutes: number;
  timezone: string;
  first_day: string;
  days: number;
  slots: AvailableSlot[];
}

/** `AppointmentTypeRead`. */
export interface AppointmentType {
  id: string;
  code: string;
  name: string;
  duration_minutes: number;
  is_active: boolean;
}

/** `DentistRead`. */
export interface Dentist {
  id: string;
  display_name: string;
  is_active: boolean;
}

/** `ClinicRead`: the token's clinic. `today` is the clinic-local calendar day. */
export interface ClinicInfo {
  id: string;
  name: string;
  timezone: string;
  today: string;
  appointment_types: AppointmentType[];
  dentists: Dentist[];
}

/** `PatientDetail`. */
export interface PatientDetail {
  patient: Patient;
  conversations: PatientConversation[];
  appointments: Appointment[];
  latest_snapshot: PatientSnapshotSummary | null;
}

export interface EscalationReasonCount {
  reason: string;
  count: number;
}

/**
 * `AnalyticsSummary`: counts from persisted conversations. `completion_rate` is completed / ended,
 * `null` before any call has ended; `average_duration_seconds` is `null` when no call has both a
 * start and an end.
 */
export interface AnalyticsSummary {
  generated_at: string;
  conversations_total: number;
  by_state: Record<ConversationState, number>;
  in_progress: number;
  ended: number;
  completed: number;
  escalated: number;
  abandoned: number;
  completion_rate: number | null;
  average_duration_seconds: number | null;
  duration_samples: number;
  escalation_reasons: EscalationReasonCount[];
}

export type LatencyStage = "stt" | "llm" | "tts" | "total";

/** `StageLatency`. Percentiles are `null` when the stage has no measurement (never 0). */
export interface StageLatency {
  stage: LatencyStage;
  samples: number;
  p50_ms: number | null;
  p95_ms: number | null;
}

/** `LatencyReport`. */
export interface LatencyReport {
  generated_at: string;
  provider_mode: ProviderMode | null;
  stages: StageLatency[];
}
