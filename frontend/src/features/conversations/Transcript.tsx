// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import type { Speaker } from "@/lib/api/types";
import { formatMs, formatTime } from "@/lib/format";

export interface TranscriptLine {
  seq: number;
  speaker: Speaker;
  text: string;
  /** Measured server-side; `null` when not measured. Shown for receptionist turns only. */
  llm_ms: number | null;
  created_at?: string;
}

const SPEAKER_LABEL: Record<Speaker, string> = { caller: "Caller", receptionist: "Receptionist" };

export function Transcript({
  lines,
  live = false,
  label = "Transcript",
}: {
  lines: TranscriptLine[];
  /** Announce new lines politely to screen readers (simulator). */
  live?: boolean;
  label?: string;
}) {
  if (lines.length === 0) {
    return <p className="text-sm text-slate-600">No turns yet.</p>;
  }
  return (
    <ol
      aria-label={label}
      role={live ? "log" : undefined}
      aria-live={live ? "polite" : undefined}
      className="space-y-3"
    >
      {lines.map((line) => {
        const caller = line.speaker === "caller";
        return (
          <li
            key={line.seq}
            className={`flex ${caller ? "justify-start" : "justify-end"}`}
            data-speaker={line.speaker}
          >
            <div
              className={`max-w-[85%] rounded-lg px-3 py-2 text-sm sm:max-w-[75%] ${
                caller
                  ? "bg-slate-100 text-slate-900"
                  : "border border-teal-200 bg-teal-50 text-slate-900"
              }`}
            >
              <p className="flex flex-wrap items-baseline gap-x-2 text-xs text-slate-600">
                <span className={`font-semibold ${caller ? "text-slate-800" : "text-teal-900"}`}>
                  {SPEAKER_LABEL[line.speaker]}
                </span>
                <span>#{line.seq}</span>
                {line.created_at ? <span>{formatTime(line.created_at)}</span> : null}
              </p>
              <p className="mt-1 whitespace-pre-wrap">{line.text}</p>
              {caller ? null : (
                <p className="mt-1 text-xs text-slate-600">
                  <abbr title="Language model response time, measured by the server">LLM</abbr>{" "}
                  <span className="tabular-nums">{formatMs(line.llm_ms)}</span>
                </p>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
