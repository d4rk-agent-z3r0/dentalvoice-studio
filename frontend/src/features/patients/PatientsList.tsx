// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
"use client";

import Link from "next/link";
import { useId, useState, type FormEvent } from "react";

import { PatientStatusBadge } from "@/components/ui/Badges";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/StateViews";
import { useApiClient } from "@/lib/api/ApiProvider";
import { PATIENT_STATUSES, type Patient, type PatientStatus } from "@/lib/api/types";
import { useApiQuery } from "@/lib/api/useApiQuery";
import { CONTACT_CHANNEL_LABELS, PATIENT_STATUS_LABELS, formatDateTime, fullName } from "@/lib/format";

export const PATIENT_PAGE_SIZE = 25;

export interface PatientFilters {
  q: string;
  status: PatientStatus | null;
  /** Zero-based. */
  page: number;
}

export function PatientsList({
  filters,
  onFiltersChange,
}: {
  filters: PatientFilters;
  onFiltersChange: (filters: PatientFilters) => void;
}) {
  const api = useApiClient();
  const searchId = useId();
  const statusId = useId();
  const [draft, setDraft] = useState(filters.q);
  const { q, status, page } = filters;
  // One extra row tells whether a next page exists without a separate count query.
  const query = useApiQuery(`patients:${q}:${status ?? "all"}:${page}`, (signal) =>
    api.listPatients(
      {
        q: q || undefined,
        status: status ?? undefined,
        limit: PATIENT_PAGE_SIZE + 1,
        offset: page * PATIENT_PAGE_SIZE,
      },
      { signal },
    ),
  );

  function onSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onFiltersChange({ q: draft.trim(), status, page: 0 });
  }

  const filtered = q !== "" || status !== null;

  return (
    <div className="space-y-4">
      <form
        role="search"
        aria-label="Patients"
        onSubmit={onSearch}
        className="flex flex-wrap items-end gap-3"
      >
        <div className="w-full sm:w-80">
          <label htmlFor={searchId} className="block text-sm font-medium text-slate-800">
            Name or email
          </label>
          <input
            id={searchId}
            type="search"
            value={draft}
            maxLength={254}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="e.g. Lindqvist or ava@example.com"
            className="field-input mt-1"
          />
        </div>
        <div>
          <label htmlFor={statusId} className="block text-sm font-medium text-slate-800">
            Status
          </label>
          <select
            id={statusId}
            value={status ?? ""}
            onChange={(event) => {
              const value = event.target.value;
              onFiltersChange({
                q,
                status: value === "" ? null : (value as PatientStatus),
                page: 0,
              });
            }}
            className="field-input mt-1 w-48 max-w-full"
          >
            <option value="">All statuses</option>
            {PATIENT_STATUSES.map((value) => (
              <option key={value} value={value}>
                {PATIENT_STATUS_LABELS[value]}
              </option>
            ))}
          </select>
        </div>
        <button type="submit" className="btn-primary">
          Search
        </button>
        {filtered ? (
          <button
            type="button"
            className="btn-secondary"
            onClick={() => {
              setDraft("");
              onFiltersChange({ q: "", status: null, page: 0 });
            }}
          >
            Clear
          </button>
        ) : null}
      </form>

      {query.status === "loading" ? <LoadingState label="Loading patients…" /> : null}
      {query.status === "error" ? (
        <ErrorState title="Patients could not be loaded." error={query.error} onRetry={query.reload} />
      ) : null}
      {query.status === "success" ? (
        <PatientsTable
          rows={query.data.slice(0, PATIENT_PAGE_SIZE)}
          page={page}
          hasNext={query.data.length > PATIENT_PAGE_SIZE}
          filtered={filtered}
          onPage={(next) => onFiltersChange({ q, status, page: next })}
        />
      ) : null}
    </div>
  );
}

function PatientsTable({
  rows,
  page,
  hasNext,
  filtered,
  onPage,
}: {
  rows: Patient[];
  page: number;
  hasNext: boolean;
  filtered: boolean;
  onPage: (page: number) => void;
}) {
  if (rows.length === 0 && page === 0) {
    return (
      <EmptyState title={filtered ? "No patients match" : "No patients yet"}>
        <p>
          {filtered
            ? "Try a different name, email or status."
            : "A patient record is created when an onboarding call completes with a confirmed intake."}
        </p>
      </EmptyState>
    );
  }
  const first = page * PATIENT_PAGE_SIZE + 1;
  return (
    <div className="card overflow-hidden">
      <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Patients table">
        <table className="w-full text-left text-sm sm:min-w-[44rem]">
          <caption className="sr-only">Patients, by last name</caption>
          <thead className="bg-slate-50 text-xs font-semibold text-slate-600 uppercase">
            <tr>
              <th scope="col" className="px-4 py-3">Patient</th>
              <th scope="col" className="hidden px-4 py-3 sm:table-cell">Contact</th>
              <th scope="col" className="px-4 py-3">Status</th>
              <th scope="col" className="hidden px-4 py-3 md:table-cell">Created</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map((patient) => (
              <tr key={patient.id} className="align-top hover:bg-slate-50">
                <td className="px-4 py-3">
                  <Link
                    href={`/patients/${patient.id}`}
                    className="font-medium text-teal-800 underline-offset-2 hover:underline"
                  >
                    {fullName(patient)}
                  </Link>
                  <span className="block text-xs text-slate-600 [overflow-wrap:anywhere] sm:hidden">
                    {patient.email ?? patient.phone ?? "—"}
                  </span>
                </td>
                <td className="hidden px-4 py-3 text-slate-700 sm:table-cell">
                  <span className="block [overflow-wrap:anywhere]">{patient.email ?? "—"}</span>
                  <span className="block">{patient.phone ?? "—"}</span>
                  {patient.preferred_contact_channel ? (
                    <span className="block text-xs text-slate-500">
                      Prefers {CONTACT_CHANNEL_LABELS[patient.preferred_contact_channel].toLowerCase()}
                    </span>
                  ) : null}
                </td>
                <td className="px-4 py-3">
                  <PatientStatusBadge status={patient.status} />
                </td>
                <td className="hidden px-4 py-3 whitespace-nowrap text-slate-700 md:table-cell">
                  {formatDateTime(patient.created_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <nav
        aria-label="Patient pages"
        className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 px-4 py-2 text-xs text-slate-600"
      >
        <span>
          {rows.length === 0 ? "No more patients." : `Showing ${first}–${first + rows.length - 1}`}
        </span>
        <span className="flex gap-2">
          <button
            type="button"
            className="btn-secondary px-2 py-1 text-xs"
            disabled={page === 0}
            onClick={() => onPage(page - 1)}
          >
            Previous
          </button>
          <button
            type="button"
            className="btn-secondary px-2 py-1 text-xs"
            disabled={!hasNext}
            onClick={() => onPage(page + 1)}
          >
            Next
          </button>
        </span>
      </nav>
    </div>
  );
}
