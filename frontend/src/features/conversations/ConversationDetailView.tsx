// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { StateBadge } from "@/components/ui/Badges";
import { PageHeader } from "@/components/ui/PageHeader";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/StateViews";
import { useApiClient } from "@/lib/api/ApiProvider";
import type { ConversationDetail, Scenario } from "@/lib/api/types";
import { useApiQuery } from "@/lib/api/useApiQuery";
import { formatDateTime, shortId } from "@/lib/format";

import { IntakeTable, MissingFields, SnapshotPanel } from "./IntakePanels";
import { StateTimeline } from "./StateTimeline";
import { Transcript } from "./Transcript";

function Panel({
  title,
  children,
  flush = false,
}: {
  title: string;
  children: ReactNode;
  flush?: boolean;
}) {
  return (
    <section aria-label={title} className="card">
      <h2 className="section-title border-b border-slate-100 px-4 py-3">{title}</h2>
      <div className={flush ? "py-2" : "p-4"}>{children}</div>
    </section>
  );
}

const backLink = (
  <Link href="/conversations" className="btn-secondary">
    All conversations
  </Link>
);

export function ConversationDetailView({ conversationId }: { conversationId: string }) {
  const api = useApiClient();
  const query = useApiQuery(`conversation:${conversationId}`, (signal) =>
    Promise.all([
      api.getConversation(conversationId, { signal }),
      api.listScenarios({ signal }),
    ]),
  );

  if (query.status === "loading") return <LoadingState label="Loading conversation…" />;
  if (query.status === "error") {
    if (query.error.code === "NOT_FOUND") {
      return (
        <EmptyState title="Conversation not found" action={backLink}>
          <p>It does not exist, or it belongs to another clinic.</p>
        </EmptyState>
      );
    }
    return (
      <div className="space-y-4">
        <ErrorState
          title="This conversation could not be loaded."
          error={query.error}
          onRetry={query.reload}
        />
        {backLink}
      </div>
    );
  }
  const [detail, scenarios] = query.data;
  return <DetailContent detail={detail} scenarios={scenarios} onReload={query.reload} />;
}

function DetailContent({
  detail,
  scenarios,
  onReload,
}: {
  detail: ConversationDetail;
  scenarios: Scenario[];
  onReload: () => void;
}) {
  const { conversation } = detail;
  const scenario = scenarios.find((item) => item.id === conversation.scenario_id);
  const meta: [string, ReactNode][] = [
    ["Scenario", scenario ? `${scenario.code} · ${scenario.title}` : "Unknown scenario"],
    ["Provider mode", conversation.provider_mode],
    ["Turns", conversation.turn_count],
    ["Created", formatDateTime(conversation.created_at)],
    ["Started", formatDateTime(conversation.started_at)],
    ["Ended", formatDateTime(conversation.ended_at)],
  ];
  return (
    <div className="space-y-6">
      <PageHeader
        title={
          <span className="flex flex-wrap items-center gap-3">
            <span>
              Conversation <span className="font-mono text-xl">{shortId(conversation.id)}</span>
            </span>
            <StateBadge state={conversation.state} />
          </span>
        }
        description={scenario?.objective}
        actions={
          <>
            {backLink}
            <button type="button" onClick={onReload} className="btn-secondary">
              Refresh
            </button>
          </>
        }
      />

      <dl className="card grid grid-cols-2 gap-x-6 gap-y-3 p-4 text-sm sm:grid-cols-3 lg:grid-cols-6">
        {meta.map(([label, value]) => (
          <div key={label} className="min-w-0">
            <dt className="text-xs text-slate-600">{label}</dt>
            <dd className="mt-0.5 font-medium break-words text-slate-900">{value}</dd>
          </div>
        ))}
      </dl>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Panel title="Transcript">
            <Transcript lines={detail.turns} />
          </Panel>
        </div>
        <div className="space-y-6">
          <Panel title="Missing fields">
            <MissingFields fields={detail.missing_fields} />
          </Panel>
          <Panel title="Confirmed snapshot">
            <SnapshotPanel snapshot={detail.snapshot} />
          </Panel>
          <Panel title="State timeline">
            <StateTimeline events={detail.events} />
          </Panel>
        </div>
      </div>

      <Panel title="Intake" flush>
        <IntakeTable drafts={detail.intake} />
      </Panel>
    </div>
  );
}
