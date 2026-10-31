// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
"use client";

import { useRouter, useSearchParams } from "next/navigation";

import { RequireSession } from "@/components/auth/RequireSession";
import { PatientsList, type PatientFilters } from "@/features/patients/PatientsList";
import { isPatientStatus } from "@/lib/api/types";

function toQuery({ q, status, page }: PatientFilters): string {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (status) params.set("status", status);
  if (page > 0) params.set("page", String(page + 1));
  return params.size > 0 ? `?${params.toString()}` : "";
}

/** Keeps search, status and page in the URL so a filtered list can be linked and reloaded. */
export function PatientsRoute() {
  const router = useRouter();
  const params = useSearchParams();
  const rawStatus = params.get("status");
  const rawPage = Number.parseInt(params.get("page") ?? "1", 10);
  const filters: PatientFilters = {
    q: (params.get("q") ?? "").trim(),
    status: rawStatus !== null && isPatientStatus(rawStatus) ? rawStatus : null,
    page: Number.isFinite(rawPage) && rawPage > 1 ? rawPage - 1 : 0,
  };
  return (
    <RequireSession>
      <PatientsList
        filters={filters}
        onFiltersChange={(next) => router.replace(`/patients${toQuery(next)}`, { scroll: false })}
      />
    </RequireSession>
  );
}
