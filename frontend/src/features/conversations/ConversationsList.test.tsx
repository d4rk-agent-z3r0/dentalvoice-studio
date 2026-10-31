// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { conversation, scenario } from "@/test/fixtures";
import { errorBody, fakeApi, renderWithProviders } from "@/test/render";

import { ConversationsList } from "./ConversationsList";

const scenarios = { status: 200, body: [scenario()] };

describe("ConversationsList", () => {
  it("shows a loading state until the API answers", async () => {
    let release: (value: { status: number; body: unknown }) => void = () => {};
    const api = fakeApi({
      "GET /api/v1/conversations": () => new Promise((resolve) => (release = resolve)),
      "GET /api/v1/scenarios": scenarios,
    });
    renderWithProviders(<ConversationsList state={null} onStateChange={vi.fn()} />, {
      fetchImpl: api.fetchImpl,
    });
    expect(screen.getByRole("status")).toHaveTextContent("Loading conversations");
    release({ status: 200, body: [] });
    expect(await screen.findByText("No conversations yet")).toBeInTheDocument();
  });

  it("lists conversations with scenario title, state, turns and a link to the detail page", async () => {
    const api = fakeApi({
      "GET /api/v1/conversations": {
        status: 200,
        body: [
          conversation({ state: "COMPLETED", turn_count: 17, ended_at: "2026-10-31T12:00:00Z" }),
          conversation({ id: "01a191cc-0000-7000-8000-00000000abcd", state: "ESCALATED", turn_count: 3 }),
        ],
      },
      "GET /api/v1/scenarios": scenarios,
    });
    renderWithProviders(<ConversationsList state={null} onStateChange={vi.fn()} />, {
      fetchImpl: api.fetchImpl,
    });

    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByRole("link")).toHaveAttribute(
      "href",
      "/conversations/01a191cc-ade4-7197-9e80-ad9477bbf4f2",
    );
    expect(rows[0]).toHaveTextContent("A · New patient: routine cleaning");
    expect(rows[0]).toHaveTextContent("Completed");
    expect(rows[0]).toHaveTextContent("17");
    expect(rows[1]).toHaveTextContent("Escalated");
    expect(api.requests[0].search).toBe("?limit=50");
  });

  it("passes the state filter to the API and reports changes", async () => {
    const onStateChange = vi.fn();
    const api = fakeApi({
      "GET /api/v1/conversations": { status: 200, body: [] },
      "GET /api/v1/scenarios": scenarios,
    });
    renderWithProviders(<ConversationsList state="ABANDONED" onStateChange={onStateChange} />, {
      fetchImpl: api.fetchImpl,
    });

    expect(await screen.findByText("No conversations in this state")).toBeInTheDocument();
    expect(api.requests[0].search).toBe("?state=ABANDONED&limit=50");
    const select = screen.getByLabelText("State");
    expect(select).toHaveValue("ABANDONED");

    fireEvent.change(select, { target: { value: "COMPLETED" } });
    expect(onStateChange).toHaveBeenLastCalledWith("COMPLETED");
    fireEvent.change(select, { target: { value: "" } });
    expect(onStateChange).toHaveBeenLastCalledWith(null);
  });

  it("shows the server's error with its request id and retries on demand", async () => {
    let calls = 0;
    const api = fakeApi({
      "GET /api/v1/conversations": () =>
        ++calls === 1
          ? { status: 503, body: errorBody("PROVIDER_UNAVAILABLE", "Database unavailable.", "rid-9") }
          : { status: 200, body: [conversation()] },
      "GET /api/v1/scenarios": scenarios,
    });
    renderWithProviders(<ConversationsList state={null} onStateChange={vi.fn()} />, {
      fetchImpl: api.fetchImpl,
    });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Conversations could not be loaded.");
    expect(alert).toHaveTextContent("Database unavailable.");
    expect(alert).toHaveTextContent("PROVIDER_UNAVAILABLE · HTTP 503 · request rid-9");

    fireEvent.click(within(alert).getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("table")).toBeInTheDocument();
  });
});
