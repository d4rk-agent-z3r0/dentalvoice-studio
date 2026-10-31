// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import type {
  AppointmentStatus,
  ContactChannel,
  ConversationState,
  IntakeField,
  IntakeFieldStatus,
  PatientStatus,
  PatientType,
} from "@/lib/api/types";

export const PATIENT_STATUS_LABELS: Record<PatientStatus, string> = {
  prospective: "Prospective",
  registered: "Registered",
  archived: "Archived",
};

export const PATIENT_TYPE_LABELS: Record<PatientType, string> = {
  new: "New patient",
  returning: "Returning patient",
};

export const CONTACT_CHANNEL_LABELS: Record<ContactChannel, string> = {
  email: "Email",
  phone: "Phone",
};

export const APPOINTMENT_STATUS_LABELS: Record<AppointmentStatus, string> = {
  requested: "Requested",
  confirmed: "Confirmed",
  cancelled: "Cancelled",
  rescheduled: "Rescheduled",
};

/** Unknown values (a newer backend) are shown as sent rather than hidden. */
export function labelOf<K extends string>(labels: Record<K, string>, value: string): string {
  return value in labels ? labels[value as K] : value;
}

export function fullName(person: { first_name: string; last_name: string }): string {
  return `${person.first_name} ${person.last_name}`;
}

const LOCAL_ISO = /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})/;

/**
 * The clinic-local calendar day of an ISO string the server already rendered in the clinic's
 * timezone (`2030-01-07T09:00:00+00:00` → `2030-01-07`). Read as written, never re-zoned.
 */
export function localDay(value: string): string {
  return LOCAL_ISO.exec(value)?.[1] ?? value;
}

/** The clinic-local wall-clock time of such a string (`…T09:00:00+00:00` → `09:00`). */
export function localClock(value: string): string {
  const match = LOCAL_ISO.exec(value);
  return match ? `${match[2]}:${match[3]}` : value;
}

/** `Mon 7 Jan 2030, 09:00` for a server-rendered clinic-local ISO string. */
export function formatLocalDateTime(value: string): string {
  const match = LOCAL_ISO.exec(value);
  return match ? `${formatCalendarDate(match[1])}, ${match[2]}:${match[3]}` : value;
}

export const FIELD_LABELS: Record<IntakeField, string> = {
  first_name: "First name",
  last_name: "Last name",
  patient_type: "Patient type",
  preferred_contact_channel: "Preferred contact",
  email: "Email",
  phone: "Phone",
  visit_reason: "Visit reason",
  requested_service: "Requested service",
  preferred_date: "Preferred date",
  preferred_time: "Preferred time",
};

/** Unknown field names (a newer backend) are shown as sent rather than hidden. */
export function fieldLabel(field: string): string {
  return field in FIELD_LABELS ? FIELD_LABELS[field as IntakeField] : field;
}

export const STATE_LABELS: Record<ConversationState, string> = {
  CREATED: "Created",
  GREETING: "Greeting",
  INTRODUCTION: "Introduction",
  IDENTITY_COLLECTION: "Identity",
  CONTACT_DETAILS: "Contact details",
  VISIT_REASON: "Visit reason",
  APPOINTMENT_PREFERENCES: "Appointment preferences",
  INFORMATION_REVIEW: "Information review",
  CONFIRMATION_PENDING: "Confirmation pending",
  COMPLETED: "Completed",
  ESCALATED: "Escalated",
  ABANDONED: "Abandoned",
};

export function stateLabel(state: string): string {
  return state in STATE_LABELS ? STATE_LABELS[state as ConversationState] : state;
}

export const STATUS_LABELS: Record<IntakeFieldStatus, string> = {
  provided: "Provided",
  not_provided: "Not provided",
  needs_confirmation: "Needs confirmation",
  confirmed: "Confirmed",
  rejected: "Rejected",
  superseded: "Superseded",
};

const dateTime = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});
const timeOnly = new Intl.DateTimeFormat("en-GB", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

/** Formats an ISO timestamp in the viewer's time zone; `—` when absent. */
export function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : dateTime.format(date);
}

export function formatTime(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : timeOnly.format(date);
}

const calendarDate = new Intl.DateTimeFormat("en-GB", {
  weekday: "short",
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

/**
 * A clinic calendar date (`YYYY-MM-DD`) is not an instant: it is formatted as-is, never shifted
 * into the viewer's time zone.
 */
export function formatCalendarDate(value: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return value;
  const [, year, month, day] = match;
  return calendarDate.format(new Date(Date.UTC(Number(year), Number(month) - 1, Number(day))));
}

/** Calendar arithmetic on `YYYY-MM-DD` days (no time zone involved). */
export function addCalendarDays(value: string, days: number): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return value;
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]) + days));
  return date.toISOString().slice(0, 10);
}

/** `HH:MM[:SS]` clinic-local time → `HH:MM`. */
export function formatClockTime(value: string): string {
  const match = /^(\d{2}):(\d{2})/.exec(value);
  return match ? `${match[1]}:${match[2]}` : value;
}

/** `125.4` → `2 min 5 s`; under ten seconds keeps one decimal (`0.234` → `0.2 s`). */
export function formatSeconds(seconds: number): string {
  if (seconds < 10) return `${seconds.toFixed(1)} s`;
  const total = Math.round(seconds);
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return minutes > 0 ? `${minutes} min ${rest} s` : `${rest} s`;
}

/** A ratio in [0, 1] as a whole percentage (`0.333…` → `33%`). */
export function formatPercent(ratio: number): string {
  return `${Math.round(ratio * 100)}%`;
}

/** A percentile in milliseconds: whole numbers from 10 ms, one decimal below. */
export function formatLatency(ms: number): string {
  return ms >= 10 ? `${Math.round(ms)} ms` : `${ms.toFixed(1)} ms`;
}

/** A measured duration in milliseconds; `—` when the server did not measure it. */
export function formatMs(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${value} ms`;
}

/**
 * Ids are UUIDv7, whose leading characters are a timestamp shared by rows created together, so the
 * random tail is the distinguishing part.
 */
export function shortId(id: string): string {
  return id.length > 8 ? `…${id.slice(-8)}` : id;
}
