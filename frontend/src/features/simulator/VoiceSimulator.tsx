// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { StateBadge } from "@/components/ui/Badges";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/StateViews";
import { useApiClient } from "@/lib/api/ApiProvider";
import type { Scenario } from "@/lib/api/types";
import { useApiQuery } from "@/lib/api/useApiQuery";
import { useAuth } from "@/lib/auth/AuthProvider";
import { shortId } from "@/lib/format";
import { browserEnvironment, type ClipOutput, type VoiceEnvironment } from "@/lib/voice/call";
import {
  activity,
  canAdvance,
  canHangUp,
  receptionistSpeaking,
  type VoiceCallState,
} from "@/lib/voice/session";

import { audioElementOutput, useVoiceCall } from "./useVoiceCall";
import {
  ActivityIndicator,
  CallErrors,
  CallSummary,
  IntakeProgress,
  LatencyTable,
  VoiceTimeline,
  VoiceTranscript,
} from "./VoicePanels";

/**
 * The voice onboarding call. Caller speech is the scenario's synthetic clips, played here and
 * streamed to speech-to-text by the server; this page never asks for the microphone.
 */
export function VoiceSimulator({
  environment = browserEnvironment,
  clipOutput,
}: {
  /** Injected in tests: fake socket, fake `AudioContext`, object URLs. */
  environment?: VoiceEnvironment;
  /** Injected in tests; the default plays clips through the hidden `<audio>` element below. */
  clipOutput?: ClipOutput;
}) {
  const [element] = useState(audioElementOutput);
  const { call, state } = useVoiceCall(environment, clipOutput ?? element);
  const { session } = useAuth();
  const viewer = session?.claims.role === "viewer";

  return (
    <>
      {/* Caller clips play here (blob URLs, revoked after playback). Not focusable, no controls. */}
      <audio ref={(audio) => element.attach(audio)} preload="auto" className="hidden" aria-hidden="true" />
      {state.conversation === null ? (
        <ScenarioStep
          state={state}
          viewer={viewer}
          onStart={(scenario) => void call.start(scenario)}
        />
      ) : (
        <CallView
          state={state}
          onNext={() => call.nextLine()}
          onHangUp={() => void call.hangUp()}
          onReconnect={() => void call.reconnect()}
          onRestart={() => call.reset()}
        />
      )}
    </>
  );
}

function ScenarioStep({
  state,
  viewer,
  onStart,
}: {
  state: VoiceCallState;
  viewer: boolean;
  onStart: (scenario: Scenario) => void;
}) {
  const api = useApiClient();
  const scenarios = useApiQuery("scenarios", (signal) => api.listScenarios({ signal }));
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const preparing = state.phase === "preparing";

  return (
    <div className="space-y-4">
      <CallErrors errors={state.errors} />
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
            if (scenario && !viewer) onStart(scenario);
          }}
        >
          <fieldset>
            <legend className="section-title">Choose a synthetic scenario</legend>
            <p className="mt-1 text-sm text-slate-600">
              The caller is a synthetic voice reading the scenario&apos;s script. Your microphone is
              never used.
            </p>
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              {scenarios.data.map((scenario) => (
                <label
                  key={scenario.id}
                  className="flex cursor-pointer gap-3 rounded-lg border border-slate-200 p-3 hover:border-teal-600 has-[:checked]:border-teal-700 has-[:checked]:bg-teal-50"
                >
                  <input
                    type="radio"
                    name="voice-scenario"
                    value={scenario.id}
                    checked={selectedId === scenario.id}
                    onChange={() => setSelectedId(scenario.id)}
                    className="mt-1 accent-teal-700"
                  />
                  <span>
                    <span className="block text-sm font-semibold text-slate-900">
                      {scenario.code} · {scenario.title}
                    </span>
                    <span className="mt-0.5 block text-sm text-slate-600">{scenario.objective}</span>
                    <span className="mt-0.5 block text-xs text-slate-600">
                      {scenario.clips.length} caller {scenario.clips.length === 1 ? "line" : "lines"}
                    </span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
          {viewer ? (
            <p className="mt-4 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
              Your role is <strong>viewer</strong>: you can review calls on the{" "}
              <Link href="/conversations" className="font-medium text-teal-800 underline underline-offset-2">
                Conversations
              </Link>{" "}
              page, but starting a call needs the staff or admin role.
            </p>
          ) : (
            <button
              type="submit"
              className="btn-primary mt-4"
              disabled={selectedId === null || preparing}
            >
              {preparing ? "Starting call…" : "Start call"}
            </button>
          )}
        </form>
      ) : null}
    </div>
  );
}

function CallView({
  state,
  onNext,
  onHangUp,
  onReconnect,
  onRestart,
}: {
  state: VoiceCallState;
  onNext: () => void;
  onHangUp: () => void;
  onReconnect: () => void;
  onRestart: () => void;
}) {
  const transcriptRef = useRef<HTMLDivElement>(null);
  const lineCount = state.lines.length + (state.interim === null ? 0 : 1);
  useEffect(() => {
    const element = transcriptRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [lineCount, state.interim]);

  const conversation = state.conversation;
  const scenario = state.scenario;
  const current = activity(state);
  const speaking = receptionistSpeaking(state);
  const ended = state.phase === "ended";
  const callerLines = state.lines.filter((line) => line.speaker === "caller").length;
  const totalLines = scenario?.clips.length ?? null;
  const latestReply = [...state.lines].reverse().find((line) => line.speaker === "receptionist");

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <section aria-labelledby="voice-call-title" className="card flex min-w-0 flex-col lg:col-span-2">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
          <div className="min-w-0">
            <h2 id="voice-call-title" className="section-title">
              {scenario ? `${scenario.code} · ${scenario.title}` : "Voice call"}
            </h2>
            <div className="mt-1">
              <ActivityIndicator activity={current} clipId={state.clip?.clipId ?? null} />
            </div>
          </div>
          {totalLines !== null ? (
            <p className="text-sm text-slate-600 tabular-nums">
              Caller line {callerLines} of {totalLines}
            </p>
          ) : null}
        </div>

        <div
          ref={transcriptRef}
          tabIndex={0}
          role="region"
          aria-label="Call transcript, scrollable"
          className="max-h-[55vh] min-h-40 flex-1 overflow-y-auto p-4"
        >
          <VoiceTranscript state={state} />
        </div>

        {/* Screen readers hear each new receptionist line once (the transcript itself is not live). */}
        <p className="sr-only" aria-live="polite" aria-atomic="true">
          {latestReply ? `Receptionist: ${latestReply.text}` : ""}
        </p>

        <div className="space-y-3 border-t border-slate-100 p-4">
          <CallErrors errors={state.errors} />
          {state.phase === "disconnected" ? (
            <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-950">
              <p className="font-semibold">The connection closed unexpectedly.</p>
              <p className="mt-1">
                {state.lastClose
                  ? `Close code ${state.lastClose.code}${state.lastClose.reason ? `: ${state.lastClose.reason}` : ""}. `
                  : ""}
                Reconnecting gets a new ticket; the call resumes with the next unanswered caller
                line.
              </p>
            </div>
          ) : null}
          {ended ? (
            <CallSummary state={state} onRestart={onRestart} />
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              {state.phase === "disconnected" ? (
                <button type="button" className="btn-primary" onClick={onReconnect}>
                  Reconnect
                </button>
              ) : (
                <button
                  type="button"
                  className="btn-primary"
                  onClick={onNext}
                  disabled={!canAdvance(state)}
                  aria-describedby={speaking ? "barge-in-hint" : undefined}
                >
                  Next caller line
                </button>
              )}
              <button
                type="button"
                className="btn-danger"
                onClick={onHangUp}
                disabled={!canHangUp(state)}
              >
                {state.phase === "ending" ? "Hanging up…" : "Hang up"}
              </button>
              {speaking && canAdvance(state) ? (
                <p id="barge-in-hint" className="text-xs text-slate-600">
                  The receptionist is speaking: the next line interrupts (barge-in).
                </p>
              ) : null}
            </div>
          )}
        </div>
      </section>

      <aside aria-label="Call status" className="card min-w-0 space-y-5 self-start p-4">
        <div>
          <h2 className="section-title">Live state</h2>
          <dl className="mt-3 space-y-2 text-sm">
            <div className="flex items-center justify-between gap-2">
              <dt className="text-slate-600">State</dt>
              <dd>{state.state ? <StateBadge state={state.state} /> : "—"}</dd>
            </div>
            {conversation ? (
              <>
                <div className="flex items-center justify-between gap-2">
                  <dt className="text-slate-600">Conversation</dt>
                  <dd>
                    <Link
                      href={`/conversations/${conversation.id}`}
                      className="font-mono text-teal-800 underline underline-offset-2"
                    >
                      {shortId(conversation.id)}
                    </Link>
                  </dd>
                </div>
                <div className="flex items-center justify-between gap-2">
                  <dt className="text-slate-600">Provider mode</dt>
                  <dd className="font-medium">{conversation.provider_mode}</dd>
                </div>
              </>
            ) : null}
            <div className="flex items-center justify-between gap-2">
              <dt className="text-slate-600">Reply audio</dt>
              <dd className="text-right font-medium">
                {state.audio
                  ? `${state.audio.encoding} · ${state.audio.sample_rate / 1000} kHz · ${state.audio.channels} ch`
                  : "—"}
              </dd>
            </div>
          </dl>
        </div>
        <div>
          <h2 className="section-title">State timeline</h2>
          <div className="mt-3">
            <VoiceTimeline state={state} />
          </div>
        </div>
        <div>
          <h2 className="section-title">Intake progress</h2>
          <div className="mt-3">
            <IntakeProgress state={state} />
          </div>
        </div>
      </aside>

      <section aria-labelledby="latency-title" className="card min-w-0 p-4 lg:col-span-2">
        <h2 id="latency-title" className="section-title">
          Measured latency
        </h2>
        <p className="mt-1 text-sm text-slate-600">
          As measured by the server for each receptionist turn. A dash means the stage did not
          happen (the greeting has no speech-to-text or model call).
        </p>
        <div className="mt-3">
          <LatencyTable state={state} />
        </div>
      </section>
    </div>
  );
}
