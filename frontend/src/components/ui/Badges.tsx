// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import type {
  AppointmentStatus,
  ConversationState,
  IntakeFieldStatus,
  PatientStatus,
} from "@/lib/api/types";
import {
  APPOINTMENT_STATUS_LABELS,
  PATIENT_STATUS_LABELS,
  STATUS_LABELS,
  labelOf,
  stateLabel,
} from "@/lib/format";

const BASE = "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap";

const STATE_TONE: Partial<Record<ConversationState, string>> = {
  CREATED: "bg-slate-100 text-slate-700 ring-1 ring-slate-300",
  COMPLETED: "bg-emerald-100 text-emerald-900",
  ESCALATED: "bg-rose-100 text-rose-900",
  ABANDONED: "bg-slate-200 text-slate-800",
};
const IN_PROGRESS = "bg-sky-100 text-sky-900";

/** The state name is always written out, so meaning never depends on colour. */
export function StateBadge({ state }: { state: ConversationState }) {
  return (
    <span className={`${BASE} ${STATE_TONE[state] ?? IN_PROGRESS}`} title={state}>
      {stateLabel(state)}
    </span>
  );
}

const STATUS_TONE: Record<IntakeFieldStatus, string> = {
  provided: "bg-sky-100 text-sky-900",
  confirmed: "bg-emerald-100 text-emerald-900",
  needs_confirmation: "bg-amber-100 text-amber-900",
  not_provided: "bg-slate-100 text-slate-700 ring-1 ring-slate-300",
  rejected: "bg-rose-100 text-rose-900",
  superseded: "bg-slate-100 text-slate-600",
};

export function StatusBadge({ status }: { status: IntakeFieldStatus }) {
  return (
    <span className={`${BASE} ${STATUS_TONE[status] ?? STATUS_TONE.provided}`}>
      {STATUS_LABELS[status] ?? status}
    </span>
  );
}

const PATIENT_STATUS_TONE: Record<PatientStatus, string> = {
  prospective: "bg-sky-100 text-sky-900",
  registered: "bg-emerald-100 text-emerald-900",
  archived: "bg-slate-200 text-slate-800",
};

export function PatientStatusBadge({ status }: { status: PatientStatus }) {
  return (
    <span className={`${BASE} ${PATIENT_STATUS_TONE[status] ?? PATIENT_STATUS_TONE.prospective}`}>
      {labelOf(PATIENT_STATUS_LABELS, status)}
    </span>
  );
}

const APPOINTMENT_STATUS_TONE: Record<AppointmentStatus, string> = {
  requested: "bg-amber-100 text-amber-900",
  confirmed: "bg-emerald-100 text-emerald-900",
  cancelled: "bg-slate-200 text-slate-800",
  rescheduled: "bg-slate-100 text-slate-700 ring-1 ring-slate-300",
};

export function AppointmentStatusBadge({ status }: { status: AppointmentStatus }) {
  return (
    <span
      className={`${BASE} ${APPOINTMENT_STATUS_TONE[status] ?? APPOINTMENT_STATUS_TONE.requested}`}
    >
      {labelOf(APPOINTMENT_STATUS_LABELS, status)}
    </span>
  );
}
