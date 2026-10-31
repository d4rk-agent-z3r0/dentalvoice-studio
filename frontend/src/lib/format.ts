// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import type { ConversationState, IntakeField, IntakeFieldStatus } from "@/lib/api/types";

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

/** `HH:MM[:SS]` clinic-local time → `HH:MM`. */
export function formatClockTime(value: string): string {
  const match = /^(\d{2}):(\d{2})/.exec(value);
  return match ? `${match[1]}:${match[2]}` : value;
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
