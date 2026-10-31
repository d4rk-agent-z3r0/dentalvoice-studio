// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
"use client";

import Link from "next/link";
import { useId } from "react";

import { StateBadge } from "@/components/ui/Badges";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/StateViews";
import { useApiClient } from "@/lib/api/ApiProvider";
import {
  CONVERSATION_STATES,
  type Conversation,
  type ConversationState,
  type Scenario,
} from "@/lib/api/types";
import { useApiQuery } from "@/lib/api/useApiQuery";
import { formatDateTime, shortId, stateLabel } from "@/lib/format";

export const CONVERSATION_PAGE_SIZE = 50;

export function ConversationsList({
  state,
  onStateChange,
}: {
  state: ConversationState | null;
  onStateChange: (state: ConversationState | null) => void;
}) {
  const api = useApiClient();
  const filterId = useId();
  const query = useApiQuery(`conversations:${state ?? "all"}`, (signal) =>
    Promise.all([
      api.listConversations(
        { state: state ?? undefined, limit: CONVERSATION_PAGE_SIZE },
        { signal },
      ),
      api.listScenarios({ signal }),
    ]),
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label htmlFor={filterId} className="block text-sm font-medium text-slate-800">
            State
          </label>
          <select
            id={filterId}
            value={state ?? ""}
            onChange={(event) => {
              const value = event.target.value;
              onStateChange(value === "" ? null : (value as ConversationState));
            }}
            className="field-input mt-1 w-64 max-w-full"
          >
            <option value="">All states</option>
            {CONVERSATION_STATES.map((value) => (
              <option key={value} value={value}>
                {stateLabel(value)}
              </option>
            ))}
          </select>
        </div>
        <button type="button" onClick={query.reload} className="btn-secondary">
          Refresh
        </button>
      </div>

      {query.status === "loading" ? <LoadingState label="Loading conversations…" /> : null}
      {query.status === "error" ? (
        <ErrorState
          title="Conversations could not be loaded."
          error={query.error}
          onRetry={query.reload}
        />
      ) : null}
      {query.status === "success" ? (
        <ConversationsTable
          conversations={query.data[0]}
          scenarios={query.data[1]}
          filtered={state !== null}
        />
      ) : null}
    </div>
  );
}

function ConversationsTable({
  conversations,
  scenarios,
  filtered,
}: {
  conversations: Conversation[];
  scenarios: Scenario[];
  filtered: boolean;
}) {
  if (conversations.length === 0) {
    return (
      <EmptyState
        title={filtered ? "No conversations in this state" : "No conversations yet"}
        action={
          <Link href="/simulator" className="btn-primary">
            Open the simulator
          </Link>
        }
      >
        <p>Conversations appear here once a call is started from the simulator.</p>
      </EmptyState>
    );
  }
  const titles = new Map(scenarios.map((scenario) => [scenario.id, scenario]));
  return (
    <div className="card overflow-hidden">
      <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Conversations table">
        <table className="w-full min-w-[44rem] text-left text-sm">
          <caption className="sr-only">
            Conversations, newest first
            {conversations.length === CONVERSATION_PAGE_SIZE
              ? ` (the ${CONVERSATION_PAGE_SIZE} most recent)`
              : ""}
          </caption>
          <thead className="bg-slate-50 text-xs font-semibold text-slate-600 uppercase">
            <tr>
              <th scope="col" className="px-4 py-3">Scenario</th>
              <th scope="col" className="px-4 py-3">State</th>
              <th scope="col" className="px-4 py-3 text-right">Turns</th>
              <th scope="col" className="px-4 py-3">Mode</th>
              <th scope="col" className="px-4 py-3">Created</th>
              <th scope="col" className="px-4 py-3">Ended</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {conversations.map((conversation) => {
              const scenario = titles.get(conversation.scenario_id);
              return (
                <tr key={conversation.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <Link
                      href={`/conversations/${conversation.id}`}
                      className="font-medium text-teal-800 underline-offset-2 hover:underline"
                    >
                      {scenario ? `${scenario.code} · ${scenario.title}` : "Unknown scenario"}
                    </Link>
                    <span className="block font-mono text-xs text-slate-500">
                      {shortId(conversation.id)}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <StateBadge state={conversation.state} />
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums">{conversation.turn_count}</td>
                  <td className="px-4 py-3 text-slate-700">{conversation.provider_mode}</td>
                  <td className="px-4 py-3 whitespace-nowrap text-slate-700">
                    {formatDateTime(conversation.created_at)}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-slate-700">
                    {formatDateTime(conversation.ended_at)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {conversations.length === CONVERSATION_PAGE_SIZE ? (
        <p className="border-t border-slate-100 px-4 py-2 text-xs text-slate-600">
          Showing the {CONVERSATION_PAGE_SIZE} most recent conversations.
        </p>
      ) : null}
    </div>
  );
}
