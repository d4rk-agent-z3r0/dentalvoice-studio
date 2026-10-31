// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import type { Metadata } from "next";
import { Suspense } from "react";

import { PageHeader } from "@/components/ui/PageHeader";
import { LoadingState } from "@/components/ui/StateViews";

import { AppointmentsRoute } from "./AppointmentsRoute";

export const metadata: Metadata = { title: "Appointments" };

export default function AppointmentsPage() {
  return (
    <>
      <PageHeader
        title="Appointments"
        description="The clinic's calendar in clinic-local time. Look up open times, book for an existing patient, cancel or reschedule. Every result shown is what the server committed."
      />
      <Suspense fallback={<LoadingState label="Loading clinic calendar…" />}>
        <AppointmentsRoute />
      </Suspense>
    </>
  );
}
