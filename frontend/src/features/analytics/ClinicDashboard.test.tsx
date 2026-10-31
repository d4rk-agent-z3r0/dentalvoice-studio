// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  CONVERSATION_STATES,
  type AnalyticsSummary,
  type ConversationState,
  type LatencyReport,
} from "@/lib/api/types";
import { formatSeconds } from "@/lib/format";
import { conversation, scenario } from "@/test/fixtures";
import { errorBody, fakeApi, renderWithProviders, type RecordedRequest } from "@/test/render";

import { ClinicDashboard, NO_DATA } from "./ClinicDashboard";

function zeroStates(): Record<ConversationState, number> {
  return Object.fromEntries(CONVERSATION_STATES.map((s) => [s, 0])) as Record<
    ConversationState,
    number
  >;
}

function summary(overrides: Partial<AnalyticsSummary> = {}): AnalyticsSummary {
  return {
    generated_at: "2026-10-31T13:30:00Z",
    conversations_total: 8,
    by_state: { ...zeroStates(), COMPLETED: 2, ESCALATED: 3, ABANDONED: 1, GREETING: 1, CREATED: 1 },
    in_progress: 2,
    ended: 6,
    completed: 2,
    escalated: 3,
    abandoned: 1,
    completion_rate: 2 / 6,
    average_duration_seconds: 125.4,
    duration_samples: 4,
    escalation_reasons: [
      { reason: "urgent_symptoms", count: 2 },
      { reason: "caller_request", count: 1 },
    ],
    ...overrides,
  };
}

function latency(overrides: Partial<LatencyReport> = {}): LatencyReport {
  return {
    generated_at: "2026-10-31T13:30:00Z",
    provider_mode: null,
    stages: [
      { stage: "stt", samples: 0, p50_ms: null, p95_ms: null },
      { stage: "llm", samples: 6, p50_ms: 350, p95_ms: 1750 },
      { stage: "tts", samples: 0, p50_ms: null, p95_ms: null },
      { stage: "total", samples: 2, p50_ms: 0.4, p95_ms: 0.96 },
    ],
    ...overrides,
  };
}

const NOTHING_MEASURED = latency({
  stages: (["stt", "llm", "tts", "total"] as const).map((stage) => ({
    stage,
    samples: 0,
    p50_ms: null,
    p95_ms: null,
  })),
});

function routes(over: Parameters<typeof fakeApi>[0] = {}) {
  return fakeApi({
    "GET /api/v1/analytics/summary": { status: 200, body: summary() },
    "GET /api/v1/analytics/latency": { status: 200, body: latency() },
    "GET /api/v1/conversations": {
      status: 200,
      body: [conversation({ state: "COMPLETED", ended_at: "2026-10-31T12:00:00Z" })],
    },
    "GET /api/v1/scenarios": { status: 200, body: [scenario()] },
    ...over,
  });
}

const latencyRequests = (requests: RecordedRequest[]) =>
  requests.filter((r) => r.path === "/api/v1/analytics/latency");

describe("ClinicDashboard", () => {
  it("shows the server's counts, completion rate, escalations and average duration", async () => {
    const api = routes();
    renderWithProviders(<ClinicDashboard />, { fetchImpl: api.fetchImpl });

    const figures = await screen.findByRole("region", { name: "Key figures" });
    const tile = (label: string) => within(figures).getByText(label).parentElement as HTMLElement;
    expect(tile("Conversations")).toHaveTextContent("8");
    expect(tile("Conversations")).toHaveTextContent("2 in progress · 6 ended");
    expect(tile("Completion rate")).toHaveTextContent("33%");
    expect(tile("Completion rate")).toHaveTextContent("2 completed of 6 ended calls");
    expect(tile("Escalations")).toHaveTextContent("3");
    expect(tile("Escalations")).toHaveTextContent("Most common reason: urgent_symptoms (2)");
    expect(tile("Average call duration")).toHaveTextContent("2 min 5 s");
    expect(tile("Average call duration")).toHaveTextContent("over 4 calls");
    expect(formatSeconds(0.2343)).toBe("0.2 s");
    expect(formatSeconds(59.6)).toBe("1 min 0 s");

    const states = within(screen.getByRole("region", { name: "Conversations by state" }));
    expect(states.getByRole("row", { name: /Escalated/ })).toHaveTextContent("3");
    expect(states.getByRole("row", { name: /Contact details/ })).toHaveTextContent("0");
    expect(states.getAllByRole("row")).toHaveLength(CONVERSATION_STATES.length + 1);

    const recent = within(screen.getByRole("region", { name: "Recent conversations" }));
    expect(recent.getByRole("link", { name: "A · New patient: routine cleaning" })).toHaveAttribute(
      "href",
      "/conversations/01a191cc-ade4-7197-9e80-ad9477bbf4f2",
    );
    expect(api.requests.find((r) => r.path === "/api/v1/conversations")?.search).toBe("?limit=5");
    expect(screen.getByRole("region", { name: "Escalation reasons" })).toHaveTextContent(
      "caller_request1",
    );
  });

  it("says 'No data yet' instead of zero when nothing has ended or been measured", async () => {
    const api = routes({
      "GET /api/v1/analytics/summary": {
        status: 200,
        body: summary({
          conversations_total: 0,
          by_state: zeroStates(),
          in_progress: 0,
          ended: 0,
          completed: 0,
          escalated: 0,
          abandoned: 0,
          completion_rate: null,
          average_duration_seconds: null,
          duration_samples: 0,
          escalation_reasons: [],
        }),
      },
      "GET /api/v1/analytics/latency": { status: 200, body: NOTHING_MEASURED },
      "GET /api/v1/conversations": { status: 200, body: [] },
    });
    renderWithProviders(<ClinicDashboard />, { fetchImpl: api.fetchImpl });

    const figures = await screen.findByRole("region", { name: "Key figures" });
    const tile = (label: string) => within(figures).getByText(label).parentElement as HTMLElement;
    expect(tile("Completion rate")).toHaveTextContent(NO_DATA);
    expect(tile("Completion rate")).not.toHaveTextContent("0%");
    expect(tile("Average call duration")).toHaveTextContent(NO_DATA);
    expect(tile("Escalations")).toHaveTextContent("No escalations recorded.");
    expect(screen.getByText(/No conversations yet. Start one from the/)).toBeInTheDocument();

    const table = await screen.findByRole("region", { name: "Latency by stage" });
    for (const row of within(table).getAllByRole("row").slice(1)) {
      expect(within(row).getAllByText(NO_DATA)).toHaveLength(2);
      expect(row).not.toHaveTextContent("0 ms");
      expect(row).toHaveTextContent(/0$/); // zero samples, stated as a count
    }
  });

  it("shows measured percentiles per stage and filters by provider mode", async () => {
    let calls = 0;
    const api = routes({
      "GET /api/v1/analytics/latency": () =>
        ++calls === 1
          ? { status: 200, body: latency() }
          : { status: 200, body: { ...NOTHING_MEASURED, provider_mode: "live" } },
    });
    renderWithProviders(<ClinicDashboard />, { fetchImpl: api.fetchImpl });

    const table = await screen.findByRole("region", { name: "Latency by stage" });
    const row = (name: string) => within(table).getByRole("row", { name: new RegExp(name) });
    expect(row("Language model")).toHaveTextContent("350 ms1750 ms6");
    expect(row("Whole turn")).toHaveTextContent("0.4 ms1.0 ms2");
    expect(row("Speech to text")).toHaveTextContent(`${NO_DATA}${NO_DATA}0`);
    expect(latencyRequests(api.requests)[0].search).toBe("");

    fireEvent.change(screen.getByLabelText("Calls"), { target: { value: "live" } });
    await waitFor(() =>
      expect(latencyRequests(api.requests).at(-1)?.search).toBe("?provider_mode=live"),
    );
    await waitFor(() =>
      expect(
        within(screen.getByRole("region", { name: "Latency by stage" })).getByRole("row", {
          name: /Language model/,
        }),
      ).toHaveTextContent(NO_DATA),
    );
  });

  it("shows errors with the server's code, independently for figures and latency", async () => {
    let attempts = 0;
    const api = routes({
      "GET /api/v1/analytics/summary": () =>
        ++attempts === 1
          ? { status: 503, body: errorBody("PROVIDER_UNAVAILABLE", "Database unavailable.", "rid-a") }
          : { status: 200, body: summary() },
      "GET /api/v1/analytics/latency": {
        status: 500,
        body: errorBody("INTERNAL_ERROR", "Something failed.", "rid-l"),
      },
    });
    renderWithProviders(<ClinicDashboard />, { fetchImpl: api.fetchImpl });

    const alerts = await screen.findAllByRole("alert");
    expect(alerts.map((a) => a.textContent)).toEqual([
      expect.stringContaining("Clinic figures could not be loaded."),
      expect.stringContaining("Latency could not be loaded."),
    ]);
    expect(alerts[0]).toHaveTextContent("PROVIDER_UNAVAILABLE · HTTP 503 · request rid-a");
    fireEvent.click(within(alerts[0]).getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("region", { name: "Key figures" })).toBeInTheDocument();
  });
});
