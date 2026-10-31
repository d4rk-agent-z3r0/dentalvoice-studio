// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
"use client";

import { useId } from "react";

import { ErrorState, LoadingState } from "@/components/ui/StateViews";
import type { ApiError } from "@/lib/api/errors";
import type { AvailableSlot } from "@/lib/api/types";
import type { QueryState } from "@/lib/api/useApiQuery";
import { formatCalendarDate, localClock } from "@/lib/format";

export function slotKey(slot: AvailableSlot): string {
  return `${slot.dentist_id}@${slot.starts_at}`;
}

/**
 * The start times the availability endpoint returned, grouped by dentist, as one radio group.
 * Availability is advisory: a time can still be taken before it is booked.
 */
export function SlotPicker({
  query,
  day,
  selected,
  onSelect,
  onRetry,
  disabled = false,
  filter,
}: {
  query: QueryState<{ slots: AvailableSlot[]; timezone: string }>;
  day: string;
  selected: string | null;
  onSelect: (slot: AvailableSlot) => void;
  onRetry: () => void;
  disabled?: boolean;
  filter?: (slot: AvailableSlot) => boolean;
}) {
  const name = useId();
  if (query.status === "loading") return <LoadingState label="Loading available times…" />;
  if (query.status === "error") {
    return <ErrorState title="Available times could not be loaded." error={query.error} onRetry={onRetry} />;
  }
  const slots = filter ? query.data.slots.filter(filter) : query.data.slots;
  if (slots.length === 0) {
    return (
      <p className="rounded-md border border-dashed border-slate-300 px-3 py-4 text-sm text-slate-600">
        No open times on {formatCalendarDate(day)}. Try another day.
      </p>
    );
  }
  const byDentist = new Map<string, { name: string; slots: AvailableSlot[] }>();
  for (const slot of slots) {
    const group = byDentist.get(slot.dentist_id) ?? { name: slot.dentist_name, slots: [] };
    group.slots.push(slot);
    byDentist.set(slot.dentist_id, group);
  }
  return (
    <fieldset disabled={disabled} className="space-y-3">
      <legend className="text-sm font-medium text-slate-800">
        Available times on {formatCalendarDate(day)}{" "}
        <span className="font-normal text-slate-600">({query.data.timezone})</span>
      </legend>
      {[...byDentist.entries()].map(([dentistId, group]) => (
        <div key={dentistId}>
          <p className="text-xs font-semibold text-slate-600">{group.name}</p>
          <div className="mt-1 flex flex-wrap gap-2">
            {group.slots.map((slot) => {
              const key = slotKey(slot);
              const checked = key === selected;
              return (
                <label
                  key={key}
                  className={`cursor-pointer rounded-md border px-2.5 py-1.5 text-sm tabular-nums has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-teal-700 ${
                    checked
                      ? "border-teal-700 bg-teal-700 font-semibold text-white"
                      : "border-slate-300 bg-white text-slate-800 hover:border-teal-600"
                  }`}
                >
                  <input
                    type="radio"
                    name={name}
                    value={key}
                    checked={checked}
                    onChange={() => onSelect(slot)}
                    className="sr-only"
                    aria-label={`${localClock(slot.starts_at_local)} to ${localClock(slot.ends_at_local)} with ${slot.dentist_name}`}
                  />
                  {localClock(slot.starts_at_local)}
                </label>
              );
            })}
          </div>
        </div>
      ))}
    </fieldset>
  );
}

/** One message per outcome the server can return for a write, with its code kept visible. */
export function writeErrorTitle(error: ApiError, action: "book" | "cancel" | "reschedule"): string {
  switch (error.code) {
    case "BOOKING_SLOT_TAKEN":
      return "That time was just taken by another booking. Available times have been refreshed; choose another.";
    case "SLOT_UNAVAILABLE":
      return "That time can no longer be booked. Available times have been refreshed.";
    case "APPOINTMENT_NOT_ACTIVE":
      return "This appointment is no longer active, so it cannot be changed. The list has been refreshed.";
    case "IDEMPOTENCY_CONFLICT":
      return "This booking request conflicts with an earlier one. Choose the time again.";
    case "NOT_FOUND":
      return "Something this request refers to no longer exists.";
    case "NETWORK_ERROR":
      return action === "book"
        ? "The API could not be reached. Trying again is safe: it reuses the same booking key."
        : "The API could not be reached.";
    default:
      if (error.status === 403) return "Your role does not allow this action.";
      return `The ${action === "book" ? "booking" : action} request failed.`;
  }
}
