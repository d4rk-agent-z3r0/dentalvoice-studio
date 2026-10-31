// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
"use client";

import Link from "next/link";
import { useId, useState, type ReactNode } from "react";

import { StateBadge } from "@/components/ui/Badges";
import { ErrorState, LoadingState } from "@/components/ui/StateViews";
import { useApiClient } from "@/lib/api/ApiProvider";
import {
  CONVERSATION_STATES,
  TERMINAL_STATES,
  type AnalyticsSummary,
  type Conversation,
  type LatencyReport,
  type LatencyStage,
  type ProviderMode,
  type Scenario,
} from "@/lib/api/types";
import { useApiQuery } from "@/lib/api/useApiQuery";
import {
  formatDateTime,
  formatLatency,
  formatPercent,
  formatSeconds,
  stateLabel,
} from "@/lib/format";

export const RECENT_CONVERSATIONS = 5;
export const NO_DATA = "No data yet";

const STAGE_LABELS: Record<LatencyStage, string> = {
  stt: "Speech to text",
  llm: "Language model",
  tts: "Text to speech",
  total: "Whole turn",
};

/**
 * The clinic dashboard. Every figure comes from the analytics and conversations endpoints, which
 * compute it from persisted rows; nothing here is invented, defaulted or estimated. A figure the
 * server reports as `null` is shown as "No data yet", never as zero.
 */
export function ClinicDashboard() {
  const api = useApiClient();
  const overview = useApiQuery("analytics:overview", (signal) =>
    Promise.all([
      api.getAnalyticsSummary({ signal }),
      api.listConversations({ limit: RECENT_CONVERSATIONS }, { signal }),
      api.listScenarios({ signal }),
    ]),
  );

  return (
    <div className="space-y-6">
      {overview.status === "loading" ? <LoadingState label="Loading clinic figures…" /> : null}
      {overview.status === "error" ? (
        <ErrorState
          title="Clinic figures could not be loaded."
          error={overview.error}
          onRetry={overview.reload}
        />
      ) : null}
      {overview.status === "success" ? (
        <Overview
          summary={overview.data[0]}
          recent={overview.data[1]}
          scenarios={overview.data[2]}
          onRefresh={overview.reload}
        />
      ) : null}
      <LatencyPanel />
    </div>
  );
}

function Tile({ label, value, detail }: { label: string; value: ReactNode; detail?: ReactNode }) {
  return (
    <div className="card p-4">
      <dt className="text-sm text-slate-600">{label}</dt>
      <dd className="mt-1 text-2xl font-semibold text-slate-900 tabular-nums">{value}</dd>
      {detail ? <dd className="mt-1 text-xs text-slate-600">{detail}</dd> : null}
    </div>
  );
}

function NoData() {
  return <span className="text-base font-medium text-slate-500">{NO_DATA}</span>;
}

function Overview({
  summary,
  recent,
  scenarios,
  onRefresh,
}: {
  summary: AnalyticsSummary;
  recent: Conversation[];
  scenarios: Scenario[];
  onRefresh: () => void;
}) {
  const topReason = summary.escalation_reasons[0];
  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-slate-600">
          Computed by the server at {formatDateTime(summary.generated_at)} from stored calls.
        </p>
        <button type="button" className="btn-secondary" onClick={onRefresh}>
          Refresh
        </button>
      </div>
      <section aria-labelledby="kpi-title">
        <h2 id="kpi-title" className="sr-only">
          Key figures
        </h2>
        <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Tile
            label="Conversations"
            value={summary.conversations_total}
            detail={`${summary.in_progress} in progress · ${summary.ended} ended`}
          />
          <Tile
            label="Completion rate"
            value={summary.completion_rate === null ? <NoData /> : formatPercent(summary.completion_rate)}
            detail={
              summary.completion_rate === null
                ? "No call has ended yet."
                : `${summary.completed} completed of ${summary.ended} ended calls`
            }
          />
          <Tile
            label="Escalations"
            value={summary.escalated}
            detail={
              topReason
                ? `Most common reason: ${topReason.reason} (${topReason.count})`
                : "No escalations recorded."
            }
          />
          <Tile
            label="Average call duration"
            value={
              summary.average_duration_seconds === null ? (
                <NoData />
              ) : (
                formatSeconds(summary.average_duration_seconds)
              )
            }
            detail={
              summary.duration_samples === 0
                ? "No call has both started and ended yet."
                : `Start to end, over ${summary.duration_samples} call${summary.duration_samples === 1 ? "" : "s"}`
            }
          />
        </dl>
      </section>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <StateBreakdown summary={summary} />
        <section aria-labelledby="recent-title" className="card min-w-0">
          <div className="flex items-center justify-between gap-2 border-b border-slate-100 px-4 py-3">
            <h2 id="recent-title" className="section-title">
              Recent conversations
            </h2>
            <Link
              href="/conversations"
              className="text-sm font-medium text-teal-800 underline-offset-2 hover:underline"
            >
              All conversations
            </Link>
          </div>
          <RecentConversations conversations={recent} scenarios={scenarios} />
        </section>
      </div>

      {summary.escalation_reasons.length > 1 ? (
        <section aria-labelledby="reasons-title" className="card p-4">
          <h2 id="reasons-title" className="section-title">
            Escalation reasons
          </h2>
          <ul className="mt-2 space-y-1 text-sm text-slate-800">
            {summary.escalation_reasons.map((item) => (
              <li key={item.reason} className="flex justify-between gap-4">
                <span className="[overflow-wrap:anywhere]">{item.reason}</span>
                <span className="tabular-nums">{item.count}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </>
  );
}

function StateBreakdown({ summary }: { summary: AnalyticsSummary }) {
  const largest = Math.max(1, ...Object.values(summary.by_state));
  return (
    <section aria-labelledby="states-title" className="card min-w-0">
      <h2 id="states-title" className="section-title border-b border-slate-100 px-4 py-3">
        Conversations by state
      </h2>
      {summary.conversations_total === 0 ? (
        <p className="p-4 text-sm text-slate-600">
          No conversations yet. Start one from the{" "}
          <Link href="/simulator" className="font-medium text-teal-800 underline">
            simulator
          </Link>
          .
        </p>
      ) : (
        <table className="w-full text-sm">
          <caption className="sr-only">Number of conversations in each state</caption>
          <thead className="sr-only">
            <tr>
              <th scope="col">State</th>
              <th scope="col">Conversations</th>
            </tr>
          </thead>
          <tbody>
            {CONVERSATION_STATES.map((state) => {
              const count = summary.by_state[state] ?? 0;
              const terminal = TERMINAL_STATES.has(state);
              return (
                <tr key={state} className={count === 0 ? "text-slate-500" : "text-slate-800"}>
                  <th scope="row" className="w-44 px-4 py-1.5 text-left font-normal whitespace-nowrap">
                    {stateLabel(state)}
                  </th>
                  <td className="px-4 py-1.5">
                    <span className="flex items-center gap-2">
                      <span className="h-2.5 flex-1 rounded-sm bg-slate-100" aria-hidden="true">
                        <span
                          className={`block h-full rounded-sm ${terminal ? "bg-teal-700" : "bg-sky-500"}`}
                          style={{ width: `${(count / largest) * 100}%` }}
                        />
                      </span>
                      <span className="w-8 text-right tabular-nums">{count}</span>
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      <p className="border-t border-slate-100 px-4 py-2 text-xs text-slate-600">
        <span className="mr-1 inline-block size-2 rounded-sm bg-sky-500" aria-hidden="true" />
        in progress
        <span className="mr-1 ml-3 inline-block size-2 rounded-sm bg-teal-700" aria-hidden="true" />
        ended
      </p>
    </section>
  );
}

function RecentConversations({
  conversations,
  scenarios,
}: {
  conversations: Conversation[];
  scenarios: Scenario[];
}) {
  if (conversations.length === 0) {
    return <p className="p-4 text-sm text-slate-600">No conversations yet.</p>;
  }
  const titles = new Map(scenarios.map((scenario) => [scenario.id, scenario]));
  return (
    <ul className="divide-y divide-slate-100">
      {conversations.map((conversation) => {
        const scenario = titles.get(conversation.scenario_id);
        return (
          <li key={conversation.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
            <span className="min-w-0">
              <Link
                href={`/conversations/${conversation.id}`}
                className="block font-medium text-teal-800 underline-offset-2 hover:underline"
              >
                {scenario ? `${scenario.code} · ${scenario.title}` : "Unknown scenario"}
              </Link>
              <span className="block text-xs text-slate-600">
                {formatDateTime(conversation.created_at)}
              </span>
            </span>
            <StateBadge state={conversation.state} />
          </li>
        );
      })}
    </ul>
  );
}

const MODE_OPTIONS: { value: ProviderMode | ""; label: string }[] = [
  { value: "", label: "All calls" },
  { value: "mock", label: "Mock provider calls" },
  { value: "live", label: "Live provider calls" },
];

function LatencyPanel() {
  const api = useApiClient();
  const modeId = useId();
  const [mode, setMode] = useState<ProviderMode | "">("");
  const query = useApiQuery(`analytics:latency:${mode || "all"}`, (signal) =>
    api.getLatency(mode || undefined, { signal }),
  );
  return (
    <section aria-labelledby="latency-title" className="card min-w-0">
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-slate-100 px-4 py-3">
        <div>
          <h2 id="latency-title" className="section-title">
            Measured latency
          </h2>
          <p className="mt-1 max-w-prose text-xs text-slate-600">
            Percentiles of the stage timings recorded on each turn. Mock-provider timings are not
            representative of a live model.
          </p>
        </div>
        <div>
          <label htmlFor={modeId} className="block text-sm font-medium text-slate-800">
            Calls
          </label>
          <select
            id={modeId}
            value={mode}
            onChange={(event) => setMode(event.target.value as ProviderMode | "")}
            className="field-input mt-1 w-56 max-w-full"
          >
            {MODE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
      </div>
      {query.status === "loading" ? (
        <div className="p-4">
          <LoadingState label="Loading latency…" />
        </div>
      ) : null}
      {query.status === "error" ? (
        <div className="p-4">
          <ErrorState title="Latency could not be loaded." error={query.error} onRetry={query.reload} />
        </div>
      ) : null}
      {query.status === "success" ? <LatencyTable report={query.data} /> : null}
    </section>
  );
}

function LatencyTable({ report }: { report: LatencyReport }) {
  return (
    <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Latency by stage">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">p50 and p95 latency per stage, in milliseconds</caption>
        <thead className="bg-slate-50 text-xs font-semibold text-slate-600 uppercase">
          <tr>
            <th scope="col" className="px-2 py-2 sm:px-4">Stage</th>
            <th scope="col" className="px-2 py-2 sm:px-4 text-right">p50</th>
            <th scope="col" className="px-2 py-2 sm:px-4 text-right">p95</th>
            <th scope="col" className="px-2 py-2 sm:px-4 text-right">Samples</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {report.stages.map((stage) => (
            <tr key={stage.stage}>
              <th scope="row" className="px-2 py-2.5 sm:px-4 font-medium text-slate-900">
                {STAGE_LABELS[stage.stage] ?? stage.stage}
              </th>
              <td className="px-2 py-2.5 text-right whitespace-nowrap tabular-nums sm:px-4">
                {stage.p50_ms === null ? <span className="text-xs text-slate-500 sm:text-sm">{NO_DATA}</span> : formatLatency(stage.p50_ms)}
              </td>
              <td className="px-2 py-2.5 text-right whitespace-nowrap tabular-nums sm:px-4">
                {stage.p95_ms === null ? <span className="text-xs text-slate-500 sm:text-sm">{NO_DATA}</span> : formatLatency(stage.p95_ms)}
              </td>
              <td className="px-2 py-2.5 sm:px-4 text-right text-slate-700 tabular-nums">{stage.samples}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
