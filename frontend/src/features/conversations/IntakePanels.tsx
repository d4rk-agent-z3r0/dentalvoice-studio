// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import { StatusBadge } from "@/components/ui/Badges";
import { INTAKE_FIELDS, type IntakeDraft, type IntakeSnapshot } from "@/lib/api/types";
import {
  fieldLabel,
  formatCalendarDate,
  formatClockTime,
  formatTime,
} from "@/lib/format";

const FIELD_ORDER = new Map<string, number>(INTAKE_FIELDS.map((field, index) => [field, index]));

function byFieldThenTime(a: IntakeDraft, b: IntakeDraft) {
  const order = (FIELD_ORDER.get(a.field) ?? 99) - (FIELD_ORDER.get(b.field) ?? 99);
  return order !== 0 ? order : a.created_at.localeCompare(b.created_at);
}

function DraftRows({ drafts }: { drafts: IntakeDraft[] }) {
  return (
    <>
      {drafts.map((draft) => (
        <tr key={draft.id} className="align-top">
          <th scope="row" className="px-3 py-3 font-medium text-slate-900 sm:px-4">
            {fieldLabel(draft.field)}
          </th>
          <td className="px-3 py-3 text-slate-800 [overflow-wrap:anywhere] sm:px-4">
            {draft.value === null ? <span className="text-slate-500">—</span> : draft.value}
          </td>
          <td className="px-3 py-3 sm:px-4">
            <StatusBadge status={draft.status} />
            {draft.rejection_reason ? (
              <p className="mt-1 text-xs text-rose-800">Reason: {draft.rejection_reason}</p>
            ) : null}
          </td>
          <td className="hidden px-4 py-3 text-right text-slate-700 tabular-nums sm:table-cell">
            {draft.confidence ?? "—"}
          </td>
          <td className="hidden px-4 py-3 whitespace-nowrap text-slate-700 sm:table-cell">
            {formatTime(draft.created_at)}
          </td>
        </tr>
      ))}
    </>
  );
}

function DraftTable({ drafts, caption }: { drafts: IntakeDraft[]; caption: string }) {
  return (
    <div className="overflow-x-auto" tabIndex={0} role="region" aria-label={caption}>
      {/* Below `sm` the confidence and time columns are hidden so field, value and status fit. */}
      <table className="w-full text-left text-sm sm:min-w-[36rem]">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-slate-50 text-xs font-semibold text-slate-600 uppercase">
          <tr>
            <th scope="col" className="px-3 py-2 sm:px-4">Field</th>
            <th scope="col" className="px-3 py-2 sm:px-4">Value</th>
            <th scope="col" className="px-3 py-2 sm:px-4">Status</th>
            <th scope="col" className="hidden px-4 py-2 text-right sm:table-cell">Confidence</th>
            <th scope="col" className="hidden px-4 py-2 sm:table-cell">Recorded</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          <DraftRows drafts={drafts} />
        </tbody>
      </table>
    </div>
  );
}

/** Every draft the backend returned: current values and rejected attempts, then corrections history. */
export function IntakeTable({ drafts }: { drafts: IntakeDraft[] }) {
  if (drafts.length === 0) {
    return <p className="px-4 pb-4 text-sm text-slate-600">No intake fields captured yet.</p>;
  }
  const current = drafts.filter((draft) => draft.status !== "superseded").sort(byFieldThenTime);
  const history = drafts.filter((draft) => draft.status === "superseded").sort(byFieldThenTime);
  return (
    <div className="space-y-4">
      <DraftTable drafts={current} caption="Intake fields" />
      {history.length > 0 ? (
        <div>
          <h3 className="px-4 text-sm font-semibold text-slate-800">
            History: superseded values ({history.length})
          </h3>
          <p className="px-4 text-xs text-slate-600">
            Values replaced by a later correction. Kept for provenance; never used.
          </p>
          <div className="mt-2">
            <DraftTable drafts={history} caption="Superseded intake values" />
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function MissingFields({ fields }: { fields: string[] }) {
  if (fields.length === 0) {
    return <p className="text-sm text-slate-600">None reported.</p>;
  }
  return (
    <ul aria-label="Missing fields" className="flex flex-wrap gap-2">
      {fields.map((field) => (
        <li
          key={field}
          className="rounded-full bg-amber-50 px-2.5 py-0.5 text-xs font-medium text-amber-900 ring-1 ring-amber-300"
        >
          {fieldLabel(field)}
        </li>
      ))}
    </ul>
  );
}

export function SnapshotPanel({ snapshot }: { snapshot: IntakeSnapshot | null }) {
  if (!snapshot) {
    return (
      <p className="text-sm text-slate-600">
        No confirmed snapshot. The backend records one only when the caller confirms the reviewed
        details and the call completes.
      </p>
    );
  }
  const rows: [string, string][] = [
    ["Name", `${snapshot.first_name} ${snapshot.last_name}`],
    ["Patient type", snapshot.patient_type],
    ["Preferred contact", snapshot.preferred_contact_channel],
    ["Email", snapshot.email ?? "—"],
    ["Phone", snapshot.phone ?? "—"],
    ["Visit reason", snapshot.visit_reason],
    ["Requested service", snapshot.requested_service],
    ["Preferred date", formatCalendarDate(snapshot.preferred_date)],
    ["Preferred time", `${formatClockTime(snapshot.preferred_time)} (clinic time)`],
  ];
  return (
    <dl aria-label="Confirmed intake snapshot" className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
      {rows.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="text-slate-600">{label}</dt>
          <dd className="font-medium break-words text-slate-900">{value}</dd>
        </div>
      ))}
    </dl>
  );
}
