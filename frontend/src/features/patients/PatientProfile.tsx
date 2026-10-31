// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { AppointmentStatusBadge, PatientStatusBadge, StateBadge } from "@/components/ui/Badges";
import { PageHeader } from "@/components/ui/PageHeader";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/StateViews";
import { namesFrom } from "@/features/appointments/names";
import { useApiClient } from "@/lib/api/ApiProvider";
import type {
  Appointment,
  ClinicInfo,
  PatientConversation,
  PatientDetail,
  PatientSnapshotSummary,
  Scenario,
} from "@/lib/api/types";
import { useApiQuery } from "@/lib/api/useApiQuery";
import { useCanWrite } from "@/lib/auth/roles";
import {
  CONTACT_CHANNEL_LABELS,
  PATIENT_TYPE_LABELS,
  formatCalendarDate,
  formatClockTime,
  formatDateTime,
  formatLocalDateTime,
  fullName,
  labelOf,
  localClock,
  shortId,
} from "@/lib/format";

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section aria-label={title} className="card">
      <h2 className="section-title border-b border-slate-100 px-4 py-3">{title}</h2>
      {children}
    </section>
  );
}

const backLink = (
  <Link href="/patients" className="btn-secondary">
    All patients
  </Link>
);

export function PatientProfile({ patientId }: { patientId: string }) {
  const api = useApiClient();
  const query = useApiQuery(`patient:${patientId}`, (signal) =>
    Promise.all([
      api.getPatient(patientId, { signal }),
      api.listScenarios({ signal }),
      api.getClinic({ signal }),
    ]),
  );

  if (query.status === "loading") return <LoadingState label="Loading patient…" />;
  if (query.status === "error") {
    if (query.error.code === "NOT_FOUND") {
      return (
        <EmptyState title="Patient not found" action={backLink}>
          <p>It does not exist, or it belongs to another clinic.</p>
        </EmptyState>
      );
    }
    return (
      <div className="space-y-4">
        <ErrorState title="This patient could not be loaded." error={query.error} onRetry={query.reload} />
        {backLink}
      </div>
    );
  }
  const [detail, scenarios, clinic] = query.data;
  return (
    <ProfileContent detail={detail} scenarios={scenarios} clinic={clinic} onReload={query.reload} />
  );
}

function ProfileContent({
  detail,
  scenarios,
  clinic,
  onReload,
}: {
  detail: PatientDetail;
  scenarios: Scenario[];
  clinic: ClinicInfo;
  onReload: () => void;
}) {
  const { patient } = detail;
  const canWrite = useCanWrite();
  const names = namesFrom(clinic);
  const contact: [string, ReactNode][] = [
    ["Email", patient.email ?? "—"],
    ["Phone", patient.phone ?? "—"],
    [
      "Preferred contact",
      patient.preferred_contact_channel
        ? CONTACT_CHANNEL_LABELS[patient.preferred_contact_channel]
        : "—",
    ],
    ["Patient type", labelOf(PATIENT_TYPE_LABELS, patient.patient_type)],
    ["Created", formatDateTime(patient.created_at)],
    ["Updated", formatDateTime(patient.updated_at)],
  ];
  return (
    <div className="space-y-6">
      <PageHeader
        title={
          <span className="flex flex-wrap items-center gap-3">
            <span>{fullName(patient)}</span>
            <PatientStatusBadge status={patient.status} />
          </span>
        }
        description="Synthetic patient record. Contact values are reserved example addresses and 555-01xx numbers."
        actions={
          <>
            {backLink}
            <button type="button" onClick={onReload} className="btn-secondary">
              Refresh
            </button>
          </>
        }
      />

      <section aria-label="Contact details" className="card">
        <h2 className="section-title border-b border-slate-100 px-4 py-3">Contact details</h2>
        <dl className="grid grid-cols-1 gap-x-6 gap-y-3 p-4 text-sm sm:grid-cols-2 lg:grid-cols-3">
          {contact.map(([label, value]) => (
            <div key={label} className="min-w-0">
              <dt className="text-xs text-slate-600">{label}</dt>
              <dd className="mt-0.5 font-medium [overflow-wrap:anywhere] text-slate-900">{value}</dd>
            </div>
          ))}
        </dl>
      </section>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-1">
          <Panel title="Latest confirmed intake">
            <SnapshotSummary snapshot={detail.latest_snapshot} />
          </Panel>
        </div>
        <div className="lg:col-span-2">
          <Panel title="Conversations">
            <ConversationRows conversations={detail.conversations} scenarios={scenarios} />
          </Panel>
        </div>
      </div>

      <Panel title="Appointments">
        <AppointmentRows
          appointments={detail.appointments}
          describe={(a) => `${names.type(a.appointment_type_id)} · ${names.dentist(a.dentist_id)}`}
        />
        {canWrite ? (
          <div className="border-t border-slate-100 px-4 py-3">
            <Link
              href={`/appointments?patient=${encodeURIComponent(patient.id)}`}
              className="btn-primary"
            >
              Book an appointment
            </Link>
          </div>
        ) : null}
      </Panel>
    </div>
  );
}

function SnapshotSummary({ snapshot }: { snapshot: PatientSnapshotSummary | null }) {
  if (!snapshot) {
    return (
      <p className="p-4 text-sm text-slate-600">
        No confirmed intake yet. One is recorded when an onboarding call for this patient completes.
      </p>
    );
  }
  const rows: [string, ReactNode][] = [
    ["Visit reason", snapshot.visit_reason],
    ["Requested service", snapshot.requested_service],
    [
      "Preferred slot",
      `${formatCalendarDate(snapshot.preferred_date)}, ${formatClockTime(snapshot.preferred_time)}`,
    ],
    ["Patient type", labelOf(PATIENT_TYPE_LABELS, snapshot.patient_type)],
    ["Preferred contact", CONTACT_CHANNEL_LABELS[snapshot.preferred_contact_channel]],
    ["Confirmed", formatDateTime(snapshot.confirmed_at)],
  ];
  return (
    <div className="p-4">
      <dl className="space-y-3 text-sm">
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt className="text-xs text-slate-600">{label}</dt>
            <dd className="mt-0.5 font-medium [overflow-wrap:anywhere] text-slate-900">{value}</dd>
          </div>
        ))}
      </dl>
      <Link
        href={`/conversations/${snapshot.conversation_id}`}
        className="mt-4 inline-block text-sm font-medium text-teal-800 underline-offset-2 hover:underline"
      >
        Open the call that confirmed it
      </Link>
    </div>
  );
}

function ConversationRows({
  conversations,
  scenarios,
}: {
  conversations: PatientConversation[];
  scenarios: Scenario[];
}) {
  if (conversations.length === 0) {
    return <p className="p-4 text-sm text-slate-600">No conversations are linked to this patient.</p>;
  }
  const titles = new Map(scenarios.map((scenario) => [scenario.id, scenario]));
  return (
    <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Linked conversations">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">Conversations linked to this patient, newest first</caption>
        <thead className="bg-slate-50 text-xs font-semibold text-slate-600 uppercase">
          <tr>
            <th scope="col" className="px-4 py-2">Call</th>
            <th scope="col" className="px-4 py-2">State</th>
            <th scope="col" className="hidden px-4 py-2 sm:table-cell">Started</th>
            <th scope="col" className="hidden px-4 py-2 sm:table-cell">Ended</th>
            <th scope="col" className="px-4 py-2">Intake</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {conversations.map((conversation) => {
            const scenario = titles.get(conversation.scenario_id);
            return (
              <tr key={conversation.id} className="align-top">
                <td className="px-4 py-3">
                  <Link
                    href={`/conversations/${conversation.id}`}
                    className="font-medium text-teal-800 underline-offset-2 hover:underline"
                  >
                    {scenario ? `${scenario.code} · ${scenario.title}` : "Unknown scenario"}
                  </Link>
                  <span className="block font-mono text-xs text-slate-500">
                    {shortId(conversation.id)}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <StateBadge state={conversation.state} />
                </td>
                <td className="hidden px-4 py-3 whitespace-nowrap text-slate-700 sm:table-cell">
                  {formatDateTime(conversation.started_at)}
                </td>
                <td className="hidden px-4 py-3 whitespace-nowrap text-slate-700 sm:table-cell">
                  {formatDateTime(conversation.ended_at)}
                </td>
                <td className="px-4 py-3 text-slate-700">
                  {conversation.snapshot_confirmed_at ? "Confirmed" : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function AppointmentRows({
  appointments,
  describe,
}: {
  appointments: Appointment[];
  /** Type and dentist names for an appointment, when the caller knows them. */
  describe?: (appointment: Appointment) => ReactNode;
}) {
  if (appointments.length === 0) {
    return <p className="p-4 text-sm text-slate-600">No appointments for this patient.</p>;
  }
  return (
    <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Patient appointments">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">
          Appointments in every status, latest first. Times are clinic-local ({appointments[0].timezone}).
        </caption>
        <thead className="bg-slate-50 text-xs font-semibold text-slate-600 uppercase">
          <tr>
            <th scope="col" className="px-4 py-2">When (clinic time)</th>
            {describe ? (
              <th scope="col" className="hidden px-4 py-2 sm:table-cell">Details</th>
            ) : null}
            <th scope="col" className="px-4 py-2">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {appointments.map((appointment) => (
            <tr key={appointment.id} className="align-top">
              <td className="px-4 py-3 text-slate-800">
                <span className="block sm:whitespace-nowrap">
                  {formatLocalDateTime(appointment.starts_at_local)}–
                  {localClock(appointment.ends_at_local)}
                </span>
                <span className="block text-xs text-slate-500">{appointment.timezone}</span>
                {describe ? (
                  <span className="block text-xs text-slate-600 sm:hidden">{describe(appointment)}</span>
                ) : null}
              </td>
              {describe ? (
                <td className="hidden px-4 py-3 text-slate-700 sm:table-cell">{describe(appointment)}</td>
              ) : null}
              <td className="px-4 py-3">
                <AppointmentStatusBadge status={appointment.status} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
