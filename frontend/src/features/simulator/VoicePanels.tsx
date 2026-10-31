// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
/** Presentational pieces of the voice simulator. They render the reducer state as reported. */
import Link from "next/link";

import { StateBadge } from "@/components/ui/Badges";
import { MissingFields } from "@/features/conversations/IntakePanels";
import { fieldLabel, formatMs, stateLabel } from "@/lib/format";
import type { Activity, VoiceCallState, VoiceError } from "@/lib/voice/session";

const SPEAKER_LABEL = { caller: "Caller", receptionist: "Receptionist" } as const;

export function VoiceTranscript({ state }: { state: VoiceCallState }) {
  const interrupted = new Set([...state.bargeIns, ...state.cancelledTurns]);
  if (state.lines.length === 0 && state.interim === null) {
    return <p className="text-sm text-slate-600">No turns yet.</p>;
  }
  return (
    <ol aria-label="Call transcript" className="space-y-3">
      {state.lines.map((line) => {
        const caller = line.speaker === "caller";
        return (
          <li
            key={`${line.speaker}-${line.seq}`}
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
                {!caller && interrupted.has(line.seq) ? (
                  <span className="rounded bg-amber-100 px-1.5 font-medium text-amber-900">
                    Speech interrupted
                  </span>
                ) : null}
              </p>
              <p className="mt-1 whitespace-pre-wrap">{line.text}</p>
            </div>
          </li>
        );
      })}
      {state.interim !== null ? (
        <li className="flex justify-start" data-speaker="caller" data-provisional="true">
          <div className="max-w-[85%] rounded-lg border border-dashed border-slate-400 bg-white px-3 py-2 text-sm sm:max-w-[75%]">
            <p className="text-xs font-semibold text-slate-700">
              Caller · <span className="font-medium">transcribing (provisional)</span>
            </p>
            <p className="mt-1 text-slate-700 italic">{state.interim}</p>
          </div>
        </li>
      ) : null}
    </ol>
  );
}

const ACTIVITY_LABEL: Record<Activity, string> = {
  idle: "Not connected",
  connecting: "Connecting…",
  greeting: "Starting the call…",
  caller_speaking: "Caller speaking",
  thinking: "Transcribing and replying…",
  receptionist_speaking: "Receptionist speaking",
  your_turn: "Waiting for the next caller line",
  ended: "Call ended",
  disconnected: "Disconnected",
};

export function ActivityIndicator({ activity, clipId }: { activity: Activity; clipId: string | null }) {
  const speaking = activity === "caller_speaking" || activity === "receptionist_speaking";
  const tone =
    activity === "disconnected"
      ? "bg-rose-50 text-rose-900 ring-rose-200"
      : speaking
        ? "bg-teal-50 text-teal-900 ring-teal-200"
        : "bg-slate-100 text-slate-800 ring-slate-200";
  return (
    <p
      className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-sm font-medium ring-1 ${tone}`}
      data-activity={activity}
    >
      <span
        aria-hidden="true"
        className={`size-2 rounded-full ${
          speaking ? "bg-teal-700 motion-safe:animate-pulse" : "bg-slate-500"
        }`}
      />
      {ACTIVITY_LABEL[activity]}
      {activity === "caller_speaking" && clipId ? (
        <span className="font-mono text-xs">({clipId})</span>
      ) : null}
    </p>
  );
}

export function LatencyTable({ state }: { state: VoiceCallState }) {
  if (state.latencies.length === 0) {
    return <p className="text-sm text-slate-600">No turn measured yet.</p>;
  }
  return (
    <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Latency per turn">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">
          Latency measured by the server for each receptionist turn. A dash means the stage did
          not happen in that turn.
        </caption>
        <thead className="bg-slate-50 text-xs font-semibold text-slate-600 uppercase">
          <tr>
            <th scope="col" className="px-2 py-2 sm:px-3">Turn</th>
            <th scope="col" className="px-2 py-2 text-right sm:px-3">
              <abbr title="Speech-to-text: end of caller audio to utterance complete">STT</abbr>
            </th>
            <th scope="col" className="px-2 py-2 text-right sm:px-3">
              <abbr title="Conversation model call, all attempts">LLM</abbr>
            </th>
            <th scope="col" className="px-2 py-2 text-right sm:px-3">
              <abbr title="Text-to-speech: synthesis request to first audio byte">TTS first byte</abbr>
            </th>
            <th scope="col" className="px-2 py-2 text-right sm:px-3">
              <abbr title="End of caller audio to first reply audio byte">Total</abbr>
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 tabular-nums">
          {state.latencies.map((row) => (
            <tr key={row.turnSeq} data-turn={row.turnSeq}>
              <th scope="row" className="px-2 py-2 font-medium whitespace-nowrap text-slate-900 sm:px-3">#{row.turnSeq}</th>
              <td className="px-2 py-2 text-right whitespace-nowrap text-slate-800 sm:px-3">{formatMs(row.stt_ms)}</td>
              <td className="px-2 py-2 text-right whitespace-nowrap text-slate-800 sm:px-3">{formatMs(row.llm_ms)}</td>
              <td className="px-2 py-2 text-right whitespace-nowrap text-slate-800 sm:px-3">
                {formatMs(row.tts_first_byte_ms)}
              </td>
              <td className="px-2 py-2 text-right font-semibold whitespace-nowrap text-slate-900 sm:px-3">
                {formatMs(row.total_ms)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function IntakeProgress({ state }: { state: VoiceCallState }) {
  const report = state.intake;
  const rejected = report ? Object.entries(report.rejected) : [];
  return (
    <div className="space-y-3">
      <div>
        <h3 className="text-sm font-semibold text-slate-800">Missing fields</h3>
        <div className="mt-2">
          {report ? (
            <MissingFields fields={report.missing} />
          ) : (
            <p className="text-sm text-slate-600">Not reported yet.</p>
          )}
        </div>
      </div>
      {rejected.length > 0 ? (
        <div>
          <h3 className="text-sm font-semibold text-slate-800">Rejected in the last turn</h3>
          <ul className="mt-1 space-y-1 text-sm text-rose-900">
            {rejected.map(([field, reason]) => (
              <li key={field}>
                <span className="font-medium">{fieldLabel(field)}:</span> {reason}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {report && report.corrected.length > 0 ? (
        <div>
          <h3 className="text-sm font-semibold text-slate-800">Corrected in the last turn</h3>
          <p className="mt-1 text-sm text-slate-700">{report.corrected.map(fieldLabel).join(", ")}</p>
        </div>
      ) : null}
      {state.intakeHistory.length > 0 ? (
        <div>
          <h3 className="text-sm font-semibold text-slate-800">During this call</h3>
          <ul aria-label="Rejections and corrections" className="mt-1 space-y-1 text-xs text-slate-700">
            {state.intakeHistory.flatMap((entry, index) => [
              ...Object.entries(entry.rejected).map(([field, reason]) => (
                <li key={`${index}-r-${field}`}>
                  {entry.turnSeq !== null ? `#${entry.turnSeq} · ` : ""}
                  <span className="font-medium text-rose-900">{fieldLabel(field)} rejected</span>:{" "}
                  {reason}
                </li>
              )),
              ...entry.corrected.map((field) => (
                <li key={`${index}-c-${field}`}>
                  {entry.turnSeq !== null ? `#${entry.turnSeq} · ` : ""}
                  <span className="font-medium text-slate-900">{fieldLabel(field)} corrected</span>
                </li>
              )),
            ])}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

export function VoiceTimeline({ state }: { state: VoiceCallState }) {
  if (state.timeline.length === 0) {
    return <p className="text-sm text-slate-600">No state changes yet.</p>;
  }
  return (
    <ol aria-label="State timeline" className="relative space-y-2 border-l border-slate-200 pl-4">
      {state.timeline.map((entry, index) => (
        <li key={index} className="relative text-sm">
          <span
            aria-hidden="true"
            className="absolute top-1.5 -left-[1.3rem] size-2.5 rounded-full border-2 border-white bg-teal-700"
          />
          <span className="font-medium text-slate-900">{stateLabel(entry.to)}</span>
          <span className="text-xs text-slate-600">
            {" "}
            from {stateLabel(entry.from)}
            {entry.turnSeq !== null ? ` · turn #${entry.turnSeq}` : ""}
          </span>
        </li>
      ))}
    </ol>
  );
}

function errorTitle(error: VoiceError): string {
  if (error.code === "PROVIDER_ERROR" || error.code === "PROVIDER_UNAVAILABLE") {
    return "A speech or language provider failed. Nothing was substituted.";
  }
  if (error.status === 403) return "This action is not allowed.";
  if (error.code === "NETWORK_ERROR") return "The API could not be reached.";
  if (error.source === "server") return "The call reported an error.";
  return "Something went wrong.";
}

/** Every error, server-sent or local, with its code verbatim. Nothing is hidden or rewritten. */
export function CallErrors({ errors }: { errors: VoiceError[] }) {
  return (
    <div role="alert" aria-label="Call errors">
      {errors.length > 0 ? (
        <ul className="space-y-2">
          {errors.map((error) => (
            <li
              key={error.id}
              className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm"
              data-code={error.code}
            >
              <p className="font-semibold text-rose-900">{errorTitle(error)}</p>
              <p className="mt-1 text-rose-900">{error.message}</p>
              <p className="mt-1 font-mono text-xs text-rose-800">
                {error.code}
                {error.provider ? ` · provider ${error.provider}` : ""}
                {error.status !== null ? ` · HTTP ${error.status}` : ""}
                {error.requestId ? ` · request ${error.requestId}` : ""}
              </p>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function CallSummary({
  state,
  onRestart,
}: {
  state: VoiceCallState;
  onRestart: () => void;
}) {
  const conversation = state.conversation;
  const finalState = state.closedState ?? state.state;
  const callerLines = state.lines.filter((line) => line.speaker === "caller").length;
  const receptionistLines = state.lines.length - callerLines;
  return (
    <section aria-labelledby="call-summary" className="rounded-lg border border-slate-200 bg-slate-50 p-4">
      <h3 id="call-summary" className="section-title">
        Call summary
      </h3>
      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
        <dt className="text-slate-600">Final state</dt>
        <dd>{finalState ? <StateBadge state={finalState} /> : "—"}</dd>
        <dt className="text-slate-600">Caller lines</dt>
        <dd className="tabular-nums">{callerLines}</dd>
        <dt className="text-slate-600">Receptionist lines</dt>
        <dd className="tabular-nums">{receptionistLines}</dd>
        <dt className="text-slate-600">Barge-ins</dt>
        <dd className="tabular-nums">{state.bargeIns.length}</dd>
        <dt className="text-slate-600">Measured turns</dt>
        <dd className="tabular-nums">{state.latencies.length}</dd>
      </dl>
      <div className="mt-3 flex flex-wrap gap-2">
        {conversation ? (
          <Link href={`/conversations/${conversation.id}`} className="btn-primary">
            View conversation details
          </Link>
        ) : null}
        <button type="button" onClick={onRestart} className="btn-secondary">
          Start another call
        </button>
      </div>
    </section>
  );
}
