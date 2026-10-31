// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ConversationDetail } from "@/lib/api/types";
import { CONVERSATION_ID, conversation, detail, draft, scenario } from "@/test/fixtures";
import { errorBody, fakeApi, renderWithProviders } from "@/test/render";

import { ConversationDetailView } from "./ConversationDetailView";

function renderDetail(body: ConversationDetail | { status: number; body: unknown }) {
  const reply = "status" in body ? body : { status: 200, body };
  const api = fakeApi({
    [`GET /api/v1/conversations/${CONVERSATION_ID}`]: reply,
    "GET /api/v1/scenarios": { status: 200, body: [scenario()] },
  });
  renderWithProviders(<ConversationDetailView conversationId={CONVERSATION_ID} />, {
    fetchImpl: api.fetchImpl,
  });
  return api;
}

describe("ConversationDetailView", () => {
  it("shows a loading state first", () => {
    renderDetail(detail());
    expect(screen.getByRole("status")).toHaveTextContent("Loading conversation");
  });

  it("renders the transcript with speakers in order", async () => {
    renderDetail(detail());
    const transcript = await screen.findByRole("list", { name: "Transcript" });
    const items = within(transcript).getAllByRole("listitem");
    expect(items.map((item) => item.dataset.speaker)).toEqual(["receptionist", "caller", "receptionist"]);
    expect(items[1]).toHaveTextContent("Caller");
    expect(items[1]).toHaveTextContent("Hi! I'd like to book a teeth cleaning, please.");
    expect(items[2]).toHaveTextContent("Receptionist");
  });

  it("shows measured LLM latency only where the server measured it", async () => {
    renderDetail(detail());
    const items = within(await screen.findByRole("list", { name: "Transcript" })).getAllByRole(
      "listitem",
    );
    expect(items[0]).toHaveTextContent("LLM —");
    expect(items[2]).toHaveTextContent("LLM 412 ms");
    // Caller turns carry no LLM figure at all.
    expect(items[1]).not.toHaveTextContent("LLM");
    // Nothing else is invented: the only millisecond figure on the page is the measured one.
    expect(screen.getAllByText(/\d+ ms/)).toHaveLength(1);
  });

  it("builds the state timeline from state_changed events only", async () => {
    renderDetail(detail());
    const timeline = await screen.findByRole("list", { name: "State timeline" });
    const steps = within(timeline).getAllByRole("listitem");
    expect(steps).toHaveLength(2);
    expect(steps[0]).toHaveTextContent("Greeting");
    expect(steps[0]).toHaveTextContent("from Created");
    expect(steps[1]).toHaveTextContent("Introduction");
    expect(steps[1]).toHaveTextContent("from Greeting");
  });

  it("lists every intake draft with its status, the rejection reason and superseded history", async () => {
    renderDetail(
      detail({
        intake: [
          draft({ field: "first_name", value: "Ava", status: "confirmed" }),
          draft({ field: "patient_type", value: "new", status: "provided" }),
          draft({ field: "phone", value: null, status: "not_provided", confidence: null }),
          draft({ field: "preferred_date", value: "2026-11-03", status: "needs_confirmation" }),
          draft({
            field: "email",
            value: "ava.lindqvist@example",
            status: "rejected",
            rejection_reason: "That is not a complete email address.",
          }),
          draft({
            field: "email",
            value: "ava.old@example.com",
            status: "superseded",
            created_at: "2026-10-31T11:51:10Z",
          }),
        ],
      }),
    );

    const current = await screen.findByRole("table", { name: "Intake fields" });
    const rows = within(current).getAllByRole("row").slice(1);
    const byField = (label: string) => rows.find((row) => within(row).queryByRole("rowheader", { name: label }));

    expect(rows).toHaveLength(5);
    expect(byField("First name")).toHaveTextContent("Confirmed");
    expect(byField("Patient type")).toHaveTextContent("Provided");
    expect(byField("Phone")).toHaveTextContent("Not provided");
    expect(byField("Phone")).toHaveTextContent("—");
    expect(byField("Preferred date")).toHaveTextContent("Needs confirmation");
    expect(byField("Email")).toHaveTextContent("Rejected");
    expect(byField("Email")).toHaveTextContent(
      "Reason: That is not a complete email address.",
    );

    const history = screen.getByRole("table", { name: "Superseded intake values" });
    const historyRows = within(history).getAllByRole("row").slice(1);
    expect(historyRows).toHaveLength(1);
    expect(historyRows[0]).toHaveTextContent("ava.old@example.com");
    expect(historyRows[0]).toHaveTextContent("Superseded");
  });

  it("shows the fields the backend reports as missing", async () => {
    renderDetail(detail({ missing_fields: ["email", "preferred_time"] }));
    const missing = await screen.findByRole("list", { name: "Missing fields" });
    expect(within(missing).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "Email",
      "Preferred time",
    ]);
  });

  it("explains that there is no snapshot for an unconfirmed call", async () => {
    renderDetail(detail({ snapshot: null }));
    expect(await screen.findByText(/No confirmed snapshot/)).toBeInTheDocument();
    expect(screen.queryByText(/confirmed\b.*booking/i)).not.toBeInTheDocument();
  });

  it("shows the confirmed snapshot of a completed call without shifting its date", async () => {
    renderDetail(
      detail({
        conversation: conversation({ state: "COMPLETED", ended_at: "2026-10-31T12:00:00Z" }),
        missing_fields: [],
        snapshot: {
          first_name: "Ava",
          last_name: "Lindqvist",
          patient_type: "new",
          preferred_contact_channel: "email",
          email: "ava.lindqvist@example.com",
          phone: "+1-555-0101",
          visit_reason: "routine cleaning",
          requested_service: "hygiene_cleaning",
          preferred_date: "2026-11-03",
          preferred_time: "10:00:00",
          provenance: {},
        },
      }),
    );
    const snapshot = await screen.findByLabelText("Confirmed intake snapshot");
    expect(snapshot).toHaveTextContent("Ava Lindqvist");
    expect(snapshot).toHaveTextContent("ava.lindqvist@example.com");
    expect(snapshot).toHaveTextContent("Tue, 3 Nov 2026");
    expect(snapshot).toHaveTextContent("10:00 (clinic time)");
    expect(screen.getByText("None reported.")).toBeInTheDocument();
    expect(screen.getAllByText("Completed").length).toBeGreaterThan(0);
  });

  it("shows a not-found state for another clinic's or unknown conversation", async () => {
    renderDetail({ status: 404, body: errorBody("NOT_FOUND", "Conversation not found.") });
    expect(await screen.findByText("Conversation not found")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "All conversations" })).toHaveAttribute(
      "href",
      "/conversations",
    );
  });

  it("shows other errors with their code and request id", async () => {
    renderDetail({ status: 500, body: errorBody("INTERNAL_ERROR", "Unexpected failure.", "rid-5") });
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("This conversation could not be loaded.");
    expect(alert).toHaveTextContent("INTERNAL_ERROR · HTTP 500 · request rid-5");
    expect(within(alert).getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});
