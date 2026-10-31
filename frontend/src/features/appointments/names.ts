// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import type { Appointment, ClinicInfo, Patient } from "@/lib/api/types";
import { formatLocalDateTime, fullName, localClock, shortId } from "@/lib/format";

export interface Names {
  patient(id: string): string | null;
  type(id: string): string;
  dentist(id: string): string;
}

/** Looks names up in reference data the server returned; an unknown id is shown, not hidden. */
export function namesFrom(clinic: ClinicInfo, patients: Patient[] = []): Names {
  const types = new Map(clinic.appointment_types.map((t) => [t.id, t.name]));
  const dentists = new Map(clinic.dentists.map((d) => [d.id, d.display_name]));
  const people = new Map(patients.map((p) => [p.id, fullName(p)]));
  return {
    patient: (id) => people.get(id) ?? null,
    type: (id) => types.get(id) ?? `Type ${shortId(id)}`,
    dentist: (id) => dentists.get(id) ?? `Dentist ${shortId(id)}`,
  };
}

/** `Mon, 7 Jan 2030, 09:00–09:30` in clinic-local time, as the server rendered it. */
export function appointmentWhen(appointment: Appointment): string {
  return `${formatLocalDateTime(appointment.starts_at_local)}–${localClock(appointment.ends_at_local)}`;
}
