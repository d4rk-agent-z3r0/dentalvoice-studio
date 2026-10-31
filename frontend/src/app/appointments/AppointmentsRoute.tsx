// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
"use client";

import { useSearchParams } from "next/navigation";

import { RequireSession } from "@/components/auth/RequireSession";
import { AppointmentsDashboard } from "@/features/appointments/AppointmentsDashboard";

/** `?patient=<id>` preselects the patient in the booking form (linked from a patient profile). */
export function AppointmentsRoute() {
  const patient = useSearchParams().get("patient");
  return (
    <RequireSession>
      <AppointmentsDashboard initialPatientId={patient} />
    </RequireSession>
  );
}
