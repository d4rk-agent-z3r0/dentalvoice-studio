// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import type { Metadata } from "next";

import { ComingSoon } from "@/components/ComingSoon";

export const metadata: Metadata = { title: "Patients" };

export default function PatientsPage() {
  return (
    <ComingSoon
      title="Patients"
      description="Synthetic patient records created from completed onboarding calls."
      dependsOn="The patient search and profile API (GET /api/v1/patients) is not available yet."
    />
  );
}
