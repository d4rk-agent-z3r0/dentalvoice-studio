// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingState } from "@/components/ui/StateViews";

import { PatientDetailRoute } from "./PatientDetailRoute";

export const metadata: Metadata = { title: "Patient" };

/** The id is only known at request time, so it is read below a Suspense boundary. */
export default function PatientPage({ params }: PageProps<"/patients/[id]">) {
  return (
    <Suspense fallback={<LoadingState label="Loading patient…" />}>
      <PatientDetailRoute params={params} />
    </Suspense>
  );
}
