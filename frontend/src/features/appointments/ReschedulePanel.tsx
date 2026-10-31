// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { useApiClient } from "@/lib/api/ApiProvider";
import { toApiError } from "@/lib/api/errors";
import type { Appointment, AvailableSlot, ClinicInfo } from "@/lib/api/types";
import { useApiQuery } from "@/lib/api/useApiQuery";
import { localDay } from "@/lib/format";

import { noAvailability } from "./BookingPanel";
import { appointmentWhen, type Names } from "./names";
import { OutcomeMessage, type Outcome } from "./Outcome";
import { SlotPicker, slotKey, writeErrorTitle } from "./SlotPicker";

/**
 * Moves an active appointment to another time with the same dentist and type. The server books the
 * new time and marks the original `rescheduled` in one transaction, and returns the new one.
 */
export function ReschedulePanel({
  clinic,
  appointment,
  names,
  onDone,
  onClose,
  onStale,
}: {
  clinic: ClinicInfo;
  appointment: Appointment;
  names: Names;
  onDone: (created: Appointment) => void;
  onClose: () => void;
  /** The appointment changed elsewhere (no longer active): the list should be refreshed. */
  onStale: () => void;
}) {
  const api = useApiClient();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const dayId = useId();
  const current = localDay(appointment.starts_at_local);
  const [day, setDay] = useState(current > clinic.today ? current : clinic.today);
  const [slot, setSlot] = useState<AvailableSlot | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const typeId = appointment.appointment_type_id;
  const availability = useApiQuery(`reschedule:${appointment.id}:${day}`, (signal) =>
    day
      ? api.getAvailability({ appointmentTypeId: typeId, date: day }, { signal })
      : Promise.resolve(noAvailability(clinic, typeId, day)),
  );

  // Move focus to the panel so keyboard and screen-reader users land on it.
  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!slot || submitting) return;
    setSubmitting(true);
    setOutcome(null);
    try {
      const created = await api.rescheduleAppointment(appointment.id, slot.starts_at);
      onDone(created);
    } catch (caught) {
      const error = toApiError(caught);
      setOutcome({ kind: "error", title: writeErrorTitle(error, "reschedule"), error });
      if (error.code === "BOOKING_SLOT_TAKEN" || error.code === "SLOT_UNAVAILABLE") {
        setSlot(null);
        availability.reload();
      }
      if (error.code === "APPOINTMENT_NOT_ACTIVE") onStale();
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4" aria-labelledby={`${dayId}-title`}>
      <div>
        <h2
          id={`${dayId}-title`}
          ref={headingRef}
          tabIndex={-1}
          className="section-title focus:outline-none"
        >
          Reschedule appointment
        </h2>
        <p className="mt-1 text-sm text-slate-700">
          {names.type(appointment.appointment_type_id)} with {names.dentist(appointment.dentist_id)}
          {" for "}
          {names.patient(appointment.patient_id) ?? "the patient"}, currently{" "}
          {appointmentWhen(appointment)}. The dentist and type stay the same.
        </p>
      </div>
      <div>
        <label htmlFor={dayId} className="block text-sm font-medium text-slate-800">
          New day (clinic time)
        </label>
        <input
          id={dayId}
          type="date"
          required
          value={day}
          min={clinic.today}
          onChange={(event) => {
            setDay(event.target.value);
            setSlot(null);
          }}
          className="field-input mt-1"
        />
      </div>
      {day ? (
        <SlotPicker
          query={availability}
          day={day}
          selected={slot ? slotKey(slot) : null}
          onSelect={setSlot}
          onRetry={availability.reload}
          disabled={submitting}
          filter={(candidate) => candidate.dentist_id === appointment.dentist_id}
        />
      ) : null}
      <div aria-live="polite">
        <OutcomeMessage outcome={outcome} />
      </div>
      <div className="flex flex-wrap gap-2">
        <button type="submit" className="btn-primary" disabled={!slot || submitting}>
          {submitting ? "Rescheduling…" : "Move appointment"}
        </button>
        <button type="button" className="btn-secondary" onClick={onClose} disabled={submitting}>
          Close
        </button>
      </div>
    </form>
  );
}
