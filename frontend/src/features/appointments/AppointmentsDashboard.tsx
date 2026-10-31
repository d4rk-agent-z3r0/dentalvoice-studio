// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
"use client";

import Link from "next/link";
import { useId, useState } from "react";

import { AppointmentStatusBadge } from "@/components/ui/Badges";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/StateViews";
import { useApiClient } from "@/lib/api/ApiProvider";
import { toApiError } from "@/lib/api/errors";
import {
  ACTIVE_APPOINTMENT_STATUSES,
  APPOINTMENT_STATUSES,
  type Appointment,
  type AppointmentStatus,
  type ClinicInfo,
  type Patient,
} from "@/lib/api/types";
import { useApiQuery } from "@/lib/api/useApiQuery";
import { useCanWrite } from "@/lib/auth/roles";
import {
  APPOINTMENT_STATUS_LABELS,
  addCalendarDays,
  formatCalendarDate,
  formatLocalDateTime,
  labelOf,
  localClock,
  localDay,
  shortId,
} from "@/lib/format";

import { BookingPanel } from "./BookingPanel";
import { appointmentWhen, namesFrom, type Names } from "./names";
import { OutcomeMessage, type Outcome } from "./Outcome";
import { ReschedulePanel } from "./ReschedulePanel";
import { writeErrorTitle } from "./SlotPicker";

/** The list endpoint's maximum page; reaching it means there may be more in the range. */
export const APPOINTMENT_LIST_LIMIT = 200;
/** Patients offered in the booking form (the list endpoint's maximum page). */
export const BOOKABLE_PATIENTS_LIMIT = 100;
/** Default range: today and the next 13 days, clinic-local. */
const DEFAULT_RANGE_DAYS = 14;

export function AppointmentsDashboard({ initialPatientId }: { initialPatientId: string | null }) {
  const api = useApiClient();
  const reference = useApiQuery("appointments:reference", (signal) =>
    Promise.all([
      api.getClinic({ signal }),
      api.listPatients({ limit: BOOKABLE_PATIENTS_LIMIT }, { signal }),
    ]),
  );
  if (reference.status === "loading") return <LoadingState label="Loading clinic calendar…" />;
  if (reference.status === "error") {
    return (
      <ErrorState
        title="The clinic calendar could not be loaded."
        error={reference.error}
        onRetry={reference.reload}
      />
    );
  }
  const [clinic, patients] = reference.data;
  return <DashboardContent clinic={clinic} patients={patients} initialPatientId={initialPatientId} />;
}

function DashboardContent({
  clinic,
  patients,
  initialPatientId,
}: {
  clinic: ClinicInfo;
  patients: Patient[];
  initialPatientId: string | null;
}) {
  const api = useApiClient();
  const canWrite = useCanWrite();
  const names = namesFrom(clinic, patients);
  const ids = { from: useId(), to: useId(), status: useId() };
  const [from, setFrom] = useState(clinic.today);
  const [to, setTo] = useState(addCalendarDays(clinic.today, DEFAULT_RANGE_DAYS - 1));
  const [status, setStatus] = useState<AppointmentStatus | null>(null);
  const [rescheduling, setRescheduling] = useState<Appointment | null>(null);
  const [confirmingCancel, setConfirmingCancel] = useState<string | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  const list = useApiQuery(`appointments:${from}:${to}:${status ?? "all"}`, (signal) =>
    api.listAppointments(
      {
        from: from || undefined,
        to: to || undefined,
        status: status ?? undefined,
        limit: APPOINTMENT_LIST_LIMIT,
      },
      { signal },
    ),
  );

  async function cancel(appointment: Appointment) {
    setPendingId(appointment.id);
    setOutcome(null);
    try {
      const cancelled = await api.cancelAppointment(appointment.id);
      setOutcome({
        kind: "success",
        message: (
          <>
            <span className="font-semibold">
              {labelOf(APPOINTMENT_STATUS_LABELS, cancelled.status)}:
            </span>{" "}
            {names.type(cancelled.appointment_type_id)} for{" "}
            {names.patient(cancelled.patient_id) ?? "the patient"}, {appointmentWhen(cancelled)}.
            The time is bookable again.
          </>
        ),
      });
      if (rescheduling?.id === appointment.id) setRescheduling(null);
    } catch (caught) {
      const error = toApiError(caught);
      setOutcome({ kind: "error", title: writeErrorTitle(error, "cancel"), error });
    } finally {
      setPendingId(null);
      setConfirmingCancel(null);
      list.reload();
    }
  }

  function onRescheduled(created: Appointment) {
    setRescheduling(null);
    setOutcome({
      kind: "success",
      message: (
        <>
          <span className="font-semibold">Rescheduled:</span> the new appointment is{" "}
          {labelOf(APPOINTMENT_STATUS_LABELS, created.status).toLowerCase()} for{" "}
          {appointmentWhen(created)}; the original is now marked rescheduled.
        </>
      ),
    });
    list.reload();
  }

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
      <section aria-labelledby="appointments-list-title" className="min-w-0 space-y-4 lg:col-span-2">
        <h2 id="appointments-list-title" className="sr-only">
          Appointments
        </h2>
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label htmlFor={ids.from} className="block text-sm font-medium text-slate-800">
              From
            </label>
            <input
              id={ids.from}
              type="date"
              value={from}
              onChange={(event) => setFrom(event.target.value)}
              className="field-input mt-1 w-44"
            />
          </div>
          <div>
            <label htmlFor={ids.to} className="block text-sm font-medium text-slate-800">
              To
            </label>
            <input
              id={ids.to}
              type="date"
              value={to}
              min={from || undefined}
              onChange={(event) => setTo(event.target.value)}
              className="field-input mt-1 w-44"
            />
          </div>
          <div>
            <label htmlFor={ids.status} className="block text-sm font-medium text-slate-800">
              Status
            </label>
            <select
              id={ids.status}
              value={status ?? ""}
              onChange={(event) => {
                const value = event.target.value;
                setStatus(value === "" ? null : (value as AppointmentStatus));
              }}
              className="field-input mt-1 w-44"
            >
              <option value="">All statuses</option>
              {APPOINTMENT_STATUSES.map((value) => (
                <option key={value} value={value}>
                  {APPOINTMENT_STATUS_LABELS[value]}
                </option>
              ))}
            </select>
          </div>
          <button type="button" className="btn-secondary" onClick={list.reload}>
            Refresh
          </button>
        </div>
        <p className="text-xs text-slate-600">
          Days and times are clinic-local ({clinic.timezone}). Today in the clinic is{" "}
          {clinic.today}.
        </p>

        <div aria-live="polite">
          <OutcomeMessage outcome={outcome} />
        </div>

        {list.status === "loading" ? <LoadingState label="Loading appointments…" /> : null}
        {list.status === "error" ? (
          <ErrorState title="Appointments could not be loaded." error={list.error} onRetry={list.reload} />
        ) : null}
        {list.status === "success" ? (
          <AppointmentsTable
            appointments={list.data}
            names={names}
            canWrite={canWrite}
            pendingId={pendingId}
            confirmingCancel={confirmingCancel}
            onAskCancel={setConfirmingCancel}
            onCancel={cancel}
            onReschedule={(appointment) => {
              setOutcome(null);
              setRescheduling(appointment);
            }}
          />
        ) : null}
      </section>

      <aside className="card h-fit min-w-0 space-y-4 p-4 lg:sticky lg:top-4" aria-label="Booking">
        {!canWrite ? (
          <div>
            <h2 className="section-title">Read-only access</h2>
            <p className="mt-1 text-sm text-slate-700">
              Your role can view appointments and availability. Booking, cancelling and rescheduling
              need a staff or admin role.
            </p>
          </div>
        ) : rescheduling ? (
          <ReschedulePanel
            key={rescheduling.id}
            clinic={clinic}
            appointment={rescheduling}
            names={names}
            onDone={onRescheduled}
            onClose={() => setRescheduling(null)}
            onStale={list.reload}
          />
        ) : (
          <>
            <h2 className="section-title">Book an appointment</h2>
            <BookingPanel
              clinic={clinic}
              patients={patients}
              names={names}
              initialPatientId={initialPatientId}
              onBooked={() => list.reload()}
              onCalendarChanged={list.reload}
            />
          </>
        )}
      </aside>
    </div>
  );
}

function AppointmentsTable({
  appointments,
  names,
  canWrite,
  pendingId,
  confirmingCancel,
  onAskCancel,
  onCancel,
  onReschedule,
}: {
  appointments: Appointment[];
  names: Names;
  canWrite: boolean;
  pendingId: string | null;
  confirmingCancel: string | null;
  onAskCancel: (id: string | null) => void;
  onCancel: (appointment: Appointment) => void;
  onReschedule: (appointment: Appointment) => void;
}) {
  if (appointments.length === 0) {
    return (
      <EmptyState title="No appointments in this range">
        <p>Change the dates or status, or book one{canWrite ? " with the form" : ""}.</p>
      </EmptyState>
    );
  }
  const showActions = canWrite && appointments.some((a) => ACTIVE_APPOINTMENT_STATUSES.has(a.status));
  return (
    <div className="card overflow-hidden">
      <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Appointments table">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">Appointments by start time, clinic-local</caption>
          <thead className="bg-slate-50 text-xs font-semibold text-slate-600 uppercase">
            <tr>
              <th scope="col" className="px-2 py-3 sm:px-4">When</th>
              <th scope="col" className="px-2 py-3 sm:px-4">Patient</th>
              <th scope="col" className="hidden px-4 py-3 md:table-cell">Type · dentist</th>
              <th scope="col" className="hidden px-4 py-3 sm:table-cell">Status</th>
              {showActions ? (
                <th scope="col" className="px-2 py-3 sm:px-4">
                  <span className="sr-only">Actions</span>
                </th>
              ) : null}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {appointments.map((appointment) => {
              const active = ACTIVE_APPOINTMENT_STATUSES.has(appointment.status);
              const patientName = names.patient(appointment.patient_id);
              const busy = pendingId === appointment.id;
              const detail = `${names.type(appointment.appointment_type_id)} · ${names.dentist(appointment.dentist_id)}`;
              return (
                <tr key={appointment.id} className="align-top">
                  <td className="px-2 py-3 sm:px-4">
                    <span className="block text-slate-900 sm:whitespace-nowrap">
                      {formatCalendarDate(localDay(appointment.starts_at_local))}
                    </span>
                    <span className="block font-medium text-slate-900 tabular-nums">
                      {localClock(appointment.starts_at_local)}–{localClock(appointment.ends_at_local)}
                    </span>
                    <span className="block text-xs text-slate-600 md:hidden">{detail}</span>
                  </td>
                  <td className="px-2 py-3 sm:px-4">
                    <Link
                      href={`/patients/${appointment.patient_id}`}
                      className="font-medium text-teal-800 underline-offset-2 hover:underline"
                    >
                      {patientName ?? `Patient ${shortId(appointment.patient_id)}`}
                    </Link>
                    {/* Below `sm` the status sits under the name, so the row fits a phone. */}
                    <span className="mt-1 block sm:hidden">
                      <AppointmentStatusBadge status={appointment.status} />
                    </span>
                  </td>
                  <td className="hidden px-4 py-3 md:table-cell">
                    <span className="block text-slate-900">
                      {names.type(appointment.appointment_type_id)}
                    </span>
                    <span className="block text-xs text-slate-600">
                      {names.dentist(appointment.dentist_id)}
                    </span>
                  </td>
                  <td className="hidden px-4 py-3 sm:table-cell">
                    <AppointmentStatusBadge status={appointment.status} />
                  </td>
                  {showActions ? (
                    <td className="px-2 py-3 sm:px-4">
                      {active ? (
                        <div className="flex flex-col items-start gap-2 sm:flex-row">
                          {confirmingCancel === appointment.id ? (
                            <>
                              <button
                                type="button"
                                className="btn-danger px-2 py-1 text-xs"
                                disabled={busy}
                                onClick={() => onCancel(appointment)}
                              >
                                {busy ? "Cancelling…" : "Confirm cancel"}
                              </button>
                              <button
                                type="button"
                                className="btn-secondary px-2 py-1 text-xs"
                                disabled={busy}
                                onClick={() => onAskCancel(null)}
                              >
                                Keep
                              </button>
                            </>
                          ) : (
                            <>
                              <button
                                type="button"
                                className="btn-secondary px-2 py-1 text-xs"
                                onClick={() => onReschedule(appointment)}
                                aria-label={`Reschedule ${patientName ?? "appointment"}, ${formatLocalDateTime(appointment.starts_at_local)}`}
                              >
                                Reschedule
                              </button>
                              <button
                                type="button"
                                className="btn-danger px-2 py-1 text-xs"
                                onClick={() => onAskCancel(appointment.id)}
                                aria-label={`Cancel ${patientName ?? "appointment"}, ${formatLocalDateTime(appointment.starts_at_local)}`}
                              >
                                Cancel
                              </button>
                            </>
                          )}
                        </div>
                      ) : null}
                    </td>
                  ) : null}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {appointments.length === APPOINTMENT_LIST_LIMIT ? (
        <p className="border-t border-slate-100 px-4 py-2 text-xs text-slate-600">
          Showing the first {APPOINTMENT_LIST_LIMIT} appointments in this range. Narrow the dates to
          see the rest.
        </p>
      ) : null}
    </div>
  );
}
