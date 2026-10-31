// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import type { Metadata } from "next";
import { Suspense } from "react";

import { PageHeader } from "@/components/ui/PageHeader";
import { LoadingState } from "@/components/ui/StateViews";

import { PatientsRoute } from "./PatientsRoute";

export const metadata: Metadata = { title: "Patients" };

export default function PatientsPage() {
  return (
    <>
      <PageHeader
        title="Patients"
        description="Synthetic patient records, created or matched when an onboarding call completes with a confirmed intake."
      />
      <Suspense fallback={<LoadingState label="Loading patients…" />}>
        <PatientsRoute />
      </Suspense>
    </>
  );
}
