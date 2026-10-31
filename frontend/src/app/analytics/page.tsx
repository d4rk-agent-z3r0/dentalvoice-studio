// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import type { Metadata } from "next";

import { RequireSession } from "@/components/auth/RequireSession";
import { PageHeader } from "@/components/ui/PageHeader";
import { ClinicDashboard } from "@/features/analytics/ClinicDashboard";

export const metadata: Metadata = { title: "Analytics" };

export default function AnalyticsPage() {
  return (
    <>
      <PageHeader
        title="Clinic dashboard"
        description="Call outcomes, durations and measured latency, computed by the server from stored conversations. Nothing here is estimated: a figure without data says so."
      />
      <RequireSession>
        <ClinicDashboard />
      </RequireSession>
    </>
  );
}
