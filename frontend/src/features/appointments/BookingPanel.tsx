// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
"use client";

import { useId, useRef, useState, type FormEvent } from "react";

import { useApiClient } from "@/lib/api/ApiProvider";
import { toApiError } from "@/lib/api/errors";
import type {
  Appointment,
  AppointmentCreate,
  Availability,
  AvailableSlot,
  ClinicInfo,
  Patient,
} from "@/lib/api/types";
import { useApiQuery } from "@/lib/api/useApiQuery";
import { APPOINTMENT_STATUS_LABELS, fullName, labelOf } from "@/lib/format";

import { appointmentWhen, type Names } from "./names";
import { OutcomeMessage, type Outcome } from "./Outcome";
import { SlotPicker, slotKey, writeErrorTitle } from "./SlotPicker";

const REFRESH_AFTER = new Set(["BOOKING_SLOT_TAKEN", "SLOT_UNAVAILABLE"]);

/** Placeholder while no day is chosen; never displayed as availability. */
export function noAvailability(clinic: ClinicInfo, typeId: string, day: string): Availability {
  return {
    appointment_type_id: typeId,
    duration_minutes: 0,
    timezone: clinic.timezone,
    first_day: day,
    days: 1,
    slots: [],
  };
}

/** A fresh key per booking intent; exported so tests can observe it. */
export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}

export function BookingPanel({
  clinic,
  patients,
  names,
  initialPatientId,
  onBooked,
  onCalendarChanged,
}: {
  clinic: ClinicInfo;
  patients: Patient[];
  names: Names;
  initialPatientId: string | null;
  onBooked: (appointment: Appointment) => void;
  /** Another booking took the time: the appointment list is out of date too. */
  onCalendarChanged: () => void;
}) {
  const api = useApiClient();
  const activeTypes = clinic.appointment_types.filter((type) => type.is_active);
  const [patientId, setPatientId] = useState(
    initialPatientId && patients.some((p) => p.id === initialPatientId)
      ? initialPatientId
      : (patients[0]?.id ?? ""),
  );
  const [typeId, setTypeId] = useState(activeTypes[0]?.id ?? "");
  const [day, setDay] = useState(clinic.today);
  const [slot, setSlot] = useState<AvailableSlot | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  // One Idempotency-Key per booking intent (patient, type, dentist, time). Retrying the same
  // intent after a failure reuses it, so a request that did commit is replayed, not repeated.
  const intentKey = useRef<{ intent: string; key: string } | null>(null);
  const ids = { patient: useId(), type: useId(), day: useId() };

  // Not called without a type and a day: the picker is only shown when both are set.
  const availability = useApiQuery(`availability:${typeId}:${day}`, (signal) =>
    typeId && day
      ? api.getAvailability({ appointmentTypeId: typeId, date: day }, { signal })
      : Promise.resolve(noAvailability(clinic, typeId, day)),
  );

  if (activeTypes.length === 0) {
    return <p className="text-sm text-slate-600">This clinic has no active appointment types to book.</p>;
  }
  if (patients.length === 0) {
    return (
      <p className="text-sm text-slate-600">
        There are no patients to book for yet. A patient record is created when an onboarding call
        completes.
      </p>
    );
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!slot || submitting) return;
    const body: AppointmentCreate = {
      patient_id: patientId,
      appointment_type_id: typeId,
      dentist_id: slot.dentist_id,
      starts_at: slot.starts_at,
      conversation_id: null,
    };
    const intent = JSON.stringify(body);
    const current =
      intentKey.current?.intent === intent
        ? intentKey.current
        : { intent, key: newIdempotencyKey() };
    intentKey.current = current;
    setSubmitting(true);
    setOutcome(null);
    try {
      const booked = await api.createAppointment(body, current.key);
      intentKey.current = null;
      setSlot(null);
      setOutcome({
        kind: "success",
        message: (
          <>
            <span className="font-semibold">
              {labelOf(APPOINTMENT_STATUS_LABELS, booked.status)}:
            </span>{" "}
            {names.type(booked.appointment_type_id)} with {names.dentist(booked.dentist_id)} for{" "}
            {names.patient(booked.patient_id) ?? "the patient"}, {appointmentWhen(booked)} (
            {booked.timezone}).
          </>
        ),
      });
      availability.reload();
      onBooked(booked);
    } catch (caught) {
      const error = toApiError(caught);
      setOutcome({ kind: "error", title: writeErrorTitle(error, "book"), error });
      if (REFRESH_AFTER.has(error.code)) {
        setSlot(null);
        availability.reload();
        onCalendarChanged();
      }
      if (error.code === "IDEMPOTENCY_CONFLICT") {
        intentKey.current = null;
        setSlot(null);
      }
    } finally {
      setSubmitting(false);
    }
  }

  const selectedKey = slot ? slotKey(slot) : null;
  return (
    <form onSubmit={onSubmit} className="space-y-4" aria-label="Book an appointment">
      <div>
        <label htmlFor={ids.patient} className="block text-sm font-medium text-slate-800">
          Patient
        </label>
        <select
          id={ids.patient}
          value={patientId}
          onChange={(event) => setPatientId(event.target.value)}
          className="field-input mt-1"
        >
          {patients.map((patient) => (
            <option key={patient.id} value={patient.id}>
              {fullName(patient)}
              {patient.email ? ` · ${patient.email}` : patient.phone ? ` · ${patient.phone}` : ""}
            </option>
          ))}
        </select>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
        <div>
          <label htmlFor={ids.type} className="block text-sm font-medium text-slate-800">
            Appointment type
          </label>
          <select
            id={ids.type}
            value={typeId}
            onChange={(event) => {
              setTypeId(event.target.value);
              setSlot(null);
            }}
            className="field-input mt-1"
          >
            {activeTypes.map((type) => (
              <option key={type.id} value={type.id}>
                {type.name} ({type.duration_minutes} min)
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor={ids.day} className="block text-sm font-medium text-slate-800">
            Day (clinic time)
          </label>
          <input
            id={ids.day}
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
      </div>

      {day ? (
        <SlotPicker
          query={availability}
          day={day}
          selected={selectedKey}
          onSelect={setSlot}
          onRetry={availability.reload}
          disabled={submitting}
        />
      ) : null}

      <div aria-live="polite">
        <OutcomeMessage outcome={outcome} />
      </div>

      <button type="submit" className="btn-primary w-full sm:w-auto" disabled={!slot || submitting}>
        {submitting ? "Booking…" : "Book appointment"}
      </button>
    </form>
  );
}
