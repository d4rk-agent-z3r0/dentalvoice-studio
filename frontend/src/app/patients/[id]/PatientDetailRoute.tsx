// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
"use client";

import { use } from "react";

import { RequireSession } from "@/components/auth/RequireSession";
import { PatientProfile } from "@/features/patients/PatientProfile";

export function PatientDetailRoute({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return (
    <RequireSession>
      <PatientProfile key={id} patientId={id} />
    </RequireSession>
  );
}
