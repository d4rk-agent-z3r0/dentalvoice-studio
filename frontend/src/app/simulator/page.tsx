// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import type { Metadata } from "next";

import { RequireSession } from "@/components/auth/RequireSession";
import { PageHeader } from "@/components/ui/PageHeader";
import { TextSimulator } from "@/features/simulator/TextSimulator";

export const metadata: Metadata = { title: "Simulator" };

export default function SimulatorPage() {
  return (
    <>
      <PageHeader
        title="Simulator"
        description="Drive a synthetic caller through the onboarding call. The receptionist's replies, state and captured fields come from the backend as they are."
      />
      <RequireSession>
        <TextSimulator />
      </RequireSession>
    </>
  );
}
