// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import type { ConversationEvent } from "@/lib/api/types";
import { formatTime, stateLabel } from "@/lib/format";

export interface StateChange {
  from: string;
  to: string;
  at: string;
}

/** `state_changed` events carry `{from, to}`; anything malformed is skipped rather than guessed. */
export function stateChanges(events: ConversationEvent[]): StateChange[] {
  return events.flatMap((event) => {
    if (event.type !== "state_changed") return [];
    const { from, to } = event.payload;
    if (typeof from !== "string" || typeof to !== "string") return [];
    return [{ from, to, at: event.created_at }];
  });
}

export function StateTimeline({ events }: { events: ConversationEvent[] }) {
  const changes = stateChanges(events);
  if (changes.length === 0) {
    return <p className="text-sm text-slate-600">No state changes recorded yet.</p>;
  }
  return (
    <ol aria-label="State timeline" className="relative space-y-3 border-l border-slate-200 pl-4">
      {changes.map((change, index) => (
        <li key={`${change.at}-${index}`} className="relative text-sm">
          <span
            aria-hidden="true"
            className="absolute top-1.5 -left-[1.3rem] size-2.5 rounded-full border-2 border-white bg-teal-700"
          />
          <p className="font-medium text-slate-900">{stateLabel(change.to)}</p>
          <p className="text-xs text-slate-600">
            from {stateLabel(change.from)} · {formatTime(change.at)}
          </p>
        </li>
      ))}
    </ol>
  );
}
