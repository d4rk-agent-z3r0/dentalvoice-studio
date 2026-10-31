// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { StateBadge } from "@/components/ui/Badges";
import { EmptyState, ErrorMeta, ErrorState, LoadingState } from "@/components/ui/StateViews";
import { MissingFields } from "@/features/conversations/IntakePanels";
import { Transcript, type TranscriptLine } from "@/features/conversations/Transcript";
import { useApiClient } from "@/lib/api/ApiProvider";
import { toApiError, type ApiError } from "@/lib/api/errors";
import {
  TERMINAL_STATES,
  type Conversation,
  type ConversationState,
  type Scenario,
  type TurnResult,
} from "@/lib/api/types";
import { useApiQuery } from "@/lib/api/useApiQuery";
import { fieldLabel, shortId, stateLabel } from "@/lib/format";

export const TEXT_MODE_LABEL =
  "Text mode (development) — synthetic voice playback arrives in Milestone 5";
const MAX_TURN_LENGTH = 500; // TextTurnCreate.text max_length

type Phase = "idle" | "starting" | "active" | "ending" | "ended";

interface Call {
  conversation: Conversation;
  scenario: Scenario;
  state: ConversationState;
  lines: TranscriptLine[];
  lastResult: TurnResult | null;
}

function receptionistLine(result: TurnResult): TranscriptLine {
  return {
    seq: result.receptionist_turn_seq,
    speaker: "receptionist",
    text: result.reply,
    llm_ms: result.llm_ms,
  };
}

export function TextSimulator() {
  const api = useApiClient();
  const scenarios = useApiQuery("scenarios", (signal) => api.listScenarios({ signal }));
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [call, setCall] = useState<Call | null>(null);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const transcriptRef = useRef<HTMLDivElement>(null);
  const inputId = useId();
  const lineCount = call?.lines.length ?? 0;

  // Keep the newest turn in view as the call progresses.
  useEffect(() => {
    const element = transcriptRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [lineCount]);

  async function startCall(scenario: Scenario) {
    setPhase("starting");
    setError(null);
    let conversation: Conversation | null = null;
    try {
      conversation = await api.createConversation(scenario.id);
      const result = await api.startConversation(conversation.id);
      setCall({
        conversation,
        scenario,
        state: result.state,
        lines: [receptionistLine(result)],
        lastResult: result,
      });
      setPhase(TERMINAL_STATES.has(result.state) ? "ended" : "active");
    } catch (caught) {
      setError(toApiError(caught));
      if (conversation) {
        setCall({ conversation, scenario, state: conversation.state, lines: [], lastResult: null });
        setPhase("ended");
      } else {
        setPhase("idle");
      }
    }
  }

  async function sendTurn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = draft.trim();
    if (!call || phase !== "active" || sending || text.length === 0) return;
    setSending(true);
    setError(null);
    try {
      const result = await api.sendTextTurn(call.conversation.id, text);
      const callerLine: TranscriptLine = {
        seq: result.caller_turn_seq ?? result.receptionist_turn_seq - 1,
        speaker: "caller",
        text,
        llm_ms: null,
      };
      setCall({
        ...call,
        state: result.state,
        lines: [...call.lines, callerLine, receptionistLine(result)],
        lastResult: result,
      });
      setDraft("");
      if (TERMINAL_STATES.has(result.state)) setPhase("ended");
    } catch (caught) {
      const apiError = toApiError(caught);
      setError(apiError);
      if (apiError.code === "CONVERSATION_CLOSED") setPhase("ended");
    } finally {
      setSending(false);
      inputRef.current?.focus();
    }
  }

  async function endCall() {
    if (!call) return;
    setPhase("ending");
    setError(null);
    try {
      const conversation = await api.endConversation(call.conversation.id);
      setCall({ ...call, conversation, state: conversation.state });
      setPhase("ended");
    } catch (caught) {
      const apiError = toApiError(caught);
      setError(apiError);
      setPhase(apiError.code === "CONVERSATION_CLOSED" ? "ended" : "active");
    }
  }

  function reset() {
    setCall(null);
    setPhase("idle");
    setDraft("");
    setError(null);
  }

  const errorAlert = error ? (
    <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm">
      <p className="font-semibold text-rose-900">{errorTitle(error)}</p>
      <p className="mt-1 text-rose-900">{error.message}</p>
      <ErrorMeta error={error} />
    </div>
  ) : null;

  if (call === null) {
    return (
      <div className="space-y-4">
        <TextModeNotice />
        {errorAlert}
        {scenarios.status === "loading" ? <LoadingState label="Loading scenarios…" /> : null}
        {scenarios.status === "error" ? (
          <ErrorState
            title="Scenarios could not be loaded."
            error={scenarios.error}
            onRetry={scenarios.reload}
          />
        ) : null}
        {scenarios.status === "success" && scenarios.data.length === 0 ? (
          <EmptyState title="No scenarios for this clinic">
            <p>Seed the synthetic demo data with make seed, then reload.</p>
          </EmptyState>
        ) : null}
        {scenarios.status === "success" && scenarios.data.length > 0 ? (
          <form
            className="card p-4"
            onSubmit={(event) => {
              event.preventDefault();
              const scenario = scenarios.data.find((item) => item.id === selectedId);
              if (scenario) void startCall(scenario);
            }}
          >
            <fieldset>
              <legend className="section-title">
                Choose a synthetic scenario
              </legend>
              <div className="mt-3 grid gap-3 md:grid-cols-2">
                {scenarios.data.map((scenario) => (
                  <label
                    key={scenario.id}
                    className="flex cursor-pointer gap-3 rounded-lg border border-slate-200 p-3 hover:border-teal-600 has-[:checked]:border-teal-700 has-[:checked]:bg-teal-50"
                  >
                    <input
                      type="radio"
                      name="scenario"
                      value={scenario.id}
                      checked={selectedId === scenario.id}
                      onChange={() => setSelectedId(scenario.id)}
                      className="mt-1 accent-teal-700"
                    />
                    <span>
                      <span className="block text-sm font-semibold text-slate-900">
                        {scenario.code} · {scenario.title}
                      </span>
                      <span className="mt-0.5 block text-sm text-slate-600">
                        {scenario.objective}
                      </span>
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>
            <button
              type="submit"
              className="btn-primary mt-4"
              disabled={selectedId === null || phase === "starting"}
            >
              {phase === "starting" ? "Starting call…" : "Start call"}
            </button>
          </form>
        ) : null}
      </div>
    );
  }

  const result = call.lastResult;
  const ended = phase === "ended";
  return (
    <div className="space-y-4">
      <TextModeNotice />
      <div className="grid gap-6 lg:grid-cols-3">
        <section aria-labelledby={`${inputId}-call`} className="card flex flex-col lg:col-span-2">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
            <h2 id={`${inputId}-call`} className="section-title">
              {call.scenario.code} · {call.scenario.title}
            </h2>
            {ended ? (
              <button type="button" onClick={reset} className="btn-secondary">
                Start another call
              </button>
            ) : (
              <button
                type="button"
                onClick={() => void endCall()}
                className="btn-danger"
                disabled={phase === "ending" || sending}
              >
                {phase === "ending" ? "Ending…" : "End call"}
              </button>
            )}
          </div>
          <div
            ref={transcriptRef}
            tabIndex={0}
            role="region"
            aria-label="Call transcript, scrollable"
            className="max-h-[60vh] flex-1 overflow-y-auto p-4"
          >
            <Transcript lines={call.lines} live label="Call transcript" />
          </div>
          <div className="space-y-3 border-t border-slate-100 p-4">
            {errorAlert}
            {ended ? (
              <p className="text-sm text-slate-700" role="status">
                The call has ended in state <strong>{stateLabel(call.state)}</strong>.{" "}
                <Link
                  href={`/conversations/${call.conversation.id}`}
                  className="font-medium text-teal-800 underline underline-offset-2"
                >
                  View conversation details
                </Link>
              </p>
            ) : (
              <form onSubmit={(event) => void sendTurn(event)} className="flex flex-col gap-2 sm:flex-row sm:items-end">
                <div className="flex-1">
                  <label htmlFor={inputId} className="block text-sm font-medium text-slate-800">
                    Caller says
                  </label>
                  <input
                    ref={inputRef}
                    id={inputId}
                    type="text"
                    value={draft}
                    onChange={(event) => setDraft(event.target.value)}
                    maxLength={MAX_TURN_LENGTH}
                    autoComplete="off"
                    aria-busy={sending}
                    className="field-input mt-1"
                    placeholder="Type what the synthetic caller says…"
                  />
                </div>
                <button
                  type="submit"
                  className="btn-primary"
                  disabled={sending || phase !== "active" || draft.trim().length === 0}
                >
                  {sending ? "Sending…" : "Send"}
                </button>
              </form>
            )}
          </div>
        </section>

        <aside aria-label="Call status" className="card space-y-4 self-start p-4">
          <div>
            <h2 className="section-title">Call status</h2>
            <dl className="mt-3 space-y-2 text-sm">
              <div className="flex items-center justify-between gap-2">
                <dt className="text-slate-600">State</dt>
                <dd>
                  <StateBadge state={call.state} />
                </dd>
              </div>
              <div className="flex items-center justify-between gap-2">
                <dt className="text-slate-600">Conversation</dt>
                <dd>
                  <Link
                    href={`/conversations/${call.conversation.id}`}
                    className="font-mono text-teal-800 underline underline-offset-2"
                  >
                    {shortId(call.conversation.id)}
                  </Link>
                </dd>
              </div>
              <div className="flex items-center justify-between gap-2">
                <dt className="text-slate-600">Provider mode</dt>
                <dd className="font-medium">{call.conversation.provider_mode}</dd>
              </div>
            </dl>
            {result && result.path.length > 0 ? (
              <p className="mt-2 text-xs text-slate-600">
                Last turn: {[result.previous_state, ...result.path].map(stateLabel).join(" → ")}
              </p>
            ) : null}
          </div>
          <div>
            <h3 className="text-sm font-semibold text-slate-800">Missing fields (last turn)</h3>
            <div className="mt-2">
              <MissingFields fields={result?.missing_fields ?? []} />
            </div>
          </div>
          {result && Object.keys(result.rejected_fields).length > 0 ? (
            <div>
              <h3 className="text-sm font-semibold text-slate-800">Rejected in the last turn</h3>
              <ul className="mt-2 space-y-1 text-sm text-rose-900">
                {Object.entries(result.rejected_fields).map(([field, reason]) => (
                  <li key={field}>
                    <span className="font-medium">{fieldLabel(field)}:</span> {reason}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {result && result.corrected_fields.length > 0 ? (
            <div>
              <h3 className="text-sm font-semibold text-slate-800">Corrected in the last turn</h3>
              <p className="mt-1 text-sm text-slate-700">
                {result.corrected_fields.map(fieldLabel).join(", ")}
              </p>
            </div>
          ) : null}
        </aside>
      </div>
    </div>
  );
}

function errorTitle(error: ApiError): string {
  if (error.code === "CONVERSATION_CLOSED") return "This call has already ended.";
  if (error.status === 403) return "This action is not allowed.";
  if (error.code === "NETWORK_ERROR") return "The API could not be reached.";
  return "The request failed.";
}

function TextModeNotice() {
  return (
    <p className="rounded-md border border-sky-200 bg-sky-50 px-3 py-2 text-sm font-medium text-sky-900">
      {TEXT_MODE_LABEL}
    </p>
  );
}
