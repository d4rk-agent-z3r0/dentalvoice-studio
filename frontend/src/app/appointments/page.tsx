// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import type { Metadata } from "next";

import { ComingSoon } from "@/components/ComingSoon";

export const metadata: Metadata = { title: "Appointments" };

export default function AppointmentsPage() {
  return (
    <ComingSoon
      title="Appointments"
      description="Appointment requests, availability and booking status."
      dependsOn="Booking (availability, reservation, cancel and reschedule) arrives with the Milestone 6 API."
    />
  );
}
