// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import type { Metadata } from "next";

import { RequireSession } from "@/components/auth/RequireSession";
import { PageHeader } from "@/components/ui/PageHeader";
import { SimulatorWorkspace } from "@/features/simulator/SimulatorWorkspace";

export const metadata: Metadata = { title: "Simulator" };

export default function SimulatorPage() {
  return (
    <>
      <PageHeader
        title="Simulator"
        description="Call a fictional clinic as a synthetic caller. You hear the scripted caller clip and the receptionist's reply; the transcript, state, intake progress and latencies are shown exactly as the server reports them."
      />
      <RequireSession>
        <SimulatorWorkspace />
      </RequireSession>
    </>
  );
}
