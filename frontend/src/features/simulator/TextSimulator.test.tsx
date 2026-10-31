// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RequireSession } from "@/components/auth/RequireSession";
import { CONVERSATION_ID, conversation, scenario, turnResult } from "@/test/fixtures";
import { errorBody, fakeApi, renderWithProviders, type Route } from "@/test/render";

import { TEXT_MODE_LABEL, TextSimulator } from "./TextSimulator";

const C = `/api/v1/conversations/${CONVERSATION_ID}`;

function simulatorApi(overrides: Record<string, Route | { status: number; body?: unknown }> = {}) {
  return fakeApi({
    "GET /api/v1/scenarios": {
      status: 200,
      body: [
        scenario(),
        scenario({ id: "s-e", code: "E", title: "Urgent symptoms: escalation", objective: "Escalate." }),
      ],
    },
    "POST /api/v1/conversations": { status: 201, body: conversation() },
    [`POST ${C}/start`]: { status: 200, body: turnResult() },
    ...overrides,
  });
}

function renderSimulator(api: ReturnType<typeof fakeApi>) {
  return renderWithProviders(
    <RequireSession>
      <TextSimulator />
    </RequireSession>,
    { fetchImpl: api.fetchImpl },
  );
}

async function startScenarioA() {
  fireEvent.click(await screen.findByRole("radio", { name: /^A · New patient/ }));
  fireEvent.click(screen.getByRole("button", { name: "Start call" }));
  return screen.findByLabelText("Caller says");
}

function say(input: HTMLElement, text: string) {
  fireEvent.change(input, { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
}

describe("TextSimulator", () => {
  it("labels itself as development text mode and lists the clinic's scenarios", async () => {
    renderSimulator(simulatorApi());
    expect(screen.getByText(TEXT_MODE_LABEL)).toBeInTheDocument();
    expect(TEXT_MODE_LABEL).toBe(
      "Text mode (development): typed caller turns without audio. The backend refuses them in production.",
    );
    expect(screen.getByRole("status")).toHaveTextContent("Loading scenarios");
    expect(await screen.findAllByRole("radio")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Start call" })).toBeDisabled();
  });

  it("shows an empty state when the clinic has no scenarios", async () => {
    renderSimulator(simulatorApi({ "GET /api/v1/scenarios": { status: 200, body: [] } }));
    expect(await screen.findByText("No scenarios for this clinic")).toBeInTheDocument();
  });

  it("creates and starts a call, then shows each reply, state and missing fields", async () => {
    const api = simulatorApi({
      [`POST ${C}/turns`]: {
        status: 200,
        body: turnResult({
          previous_state: "GREETING",
          state: "IDENTITY_COLLECTION",
          path: ["INTRODUCTION", "IDENTITY_COLLECTION"],
          reply: "Happy to help with that. Could I have your first and last name?",
          caller_turn_seq: 2,
          receptionist_turn_seq: 3,
          missing_fields: ["first_name", "last_name"],
          llm_ms: 0,
        }),
      },
    });
    renderSimulator(api);
    const input = await startScenarioA();

    expect(api.requests.map((r) => `${r.method} ${r.path}`)).toEqual([
      "GET /api/v1/scenarios",
      "POST /api/v1/conversations",
      `POST ${C}/start`,
    ]);
    expect(api.requests[1].body).toEqual({ scenario_id: scenario().id });
    const log = screen.getByRole("log");
    expect(log).toHaveTextContent("Welcome to BrightSmile Dental Studio");
    expect(log).toHaveTextContent("LLM —");

    say(input, "Hi! I'd like to book a teeth cleaning, please. I'm a new patient.");

    expect(await within(log).findByText(/Could I have your first and last name\?/)).toBeInTheDocument();
    expect(api.requests.at(-1)?.body).toEqual({
      text: "Hi! I'd like to book a teeth cleaning, please. I'm a new patient.",
    });
    const items = within(log).getAllByRole("listitem");
    expect(items.map((item) => item.dataset.speaker)).toEqual(["receptionist", "caller", "receptionist"]);
    expect(items[2]).toHaveTextContent("LLM 0 ms");
    const status = screen.getByRole("complementary", { name: "Call status" });
    expect(status).toHaveTextContent("Identity");
    expect(status).toHaveTextContent("Greeting → Introduction → Identity");
    expect(within(status).getByRole("list", { name: "Missing fields" })).toHaveTextContent(
      "First nameLast name",
    );
    expect(input).toHaveValue("");
  });

  it("shows fields the backend rejected with its reason", async () => {
    renderSimulator(
      simulatorApi({
        [`POST ${C}/turns`]: {
          status: 200,
          body: turnResult({
            previous_state: "CONTACT_DETAILS",
            state: "CONTACT_DETAILS",
            path: [],
            reply: "I can only accept example addresses in this demo.",
            caller_turn_seq: 6,
            receptionist_turn_seq: 7,
            rejected_fields: { email: "Only reserved example domains are allowed." },
          }),
        },
      }),
    );
    say(await startScenarioA(), "My email is ava at example.");
    expect(await screen.findByText("Rejected in the last turn")).toBeInTheDocument();
    expect(screen.getByText(/Only reserved example domains are allowed\./)).toBeInTheDocument();
  });

  it("ends the call on request and links to the conversation", async () => {
    const api = simulatorApi({
      [`POST ${C}/end`]: { status: 200, body: conversation({ state: "ABANDONED" }) },
    });
    renderSimulator(api);
    await startScenarioA();

    fireEvent.click(screen.getByRole("button", { name: "End call" }));

    expect(await screen.findByText(/The call has ended in state/)).toHaveTextContent("Abandoned");
    expect(screen.queryByLabelText("Caller says")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View conversation details" })).toHaveAttribute(
      "href",
      `/conversations/${CONVERSATION_ID}`,
    );
    expect(api.requests.at(-1)?.path).toBe(`${C}/end`);
  });

  it("stops at a terminal state and never claims more than the backend said", async () => {
    renderSimulator(
      simulatorApi({
        [`POST ${C}/turns`]: {
          status: 200,
          body: turnResult({
            previous_state: "CONFIRMATION_PENDING",
            state: "COMPLETED",
            path: ["COMPLETED"],
            reply: "All set. Your request has been recorded.",
            caller_turn_seq: 16,
            receptionist_turn_seq: 17,
          }),
        },
      }),
    );
    say(await startScenarioA(), "Yes, please go ahead and confirm it.");
    expect(await screen.findByText(/The call has ended in state/)).toHaveTextContent("Completed");
    expect(screen.queryByText(/booking confirmed|appointment confirmed|booked/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start another call" })).toBeInTheDocument();
  });

  it("explains a 403 (typed turns disabled) and keeps the caller's text", async () => {
    renderSimulator(
      simulatorApi({
        [`POST ${C}/turns`]: {
          status: 403,
          body: errorBody("FORBIDDEN", "Typed turns are disabled in this environment.", "rid-403"),
        },
      }),
    );
    const input = await startScenarioA();
    say(input, "Hello?");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("This action is not allowed.");
    expect(alert).toHaveTextContent("Typed turns are disabled in this environment.");
    expect(alert).toHaveTextContent("FORBIDDEN · HTTP 403 · request rid-403");
    expect(input).toHaveValue("Hello?");
    expect(screen.getByRole("button", { name: "End call" })).toBeEnabled();
  });

  it("explains a 403 for a viewer who cannot start calls", async () => {
    renderSimulator(
      simulatorApi({
        "POST /api/v1/conversations": {
          status: 403,
          body: errorBody("FORBIDDEN", "Your role does not allow this action."),
        },
      }),
    );
    await screen.findAllByRole("radio");
    fireEvent.click(screen.getByRole("radio", { name: /^A · New patient/ }));
    fireEvent.click(screen.getByRole("button", { name: "Start call" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Your role does not allow this action.");
    expect(screen.getByRole("button", { name: "Start call" })).toBeEnabled();
  });

  it("treats 409 CONVERSATION_CLOSED as the end of the call", async () => {
    renderSimulator(
      simulatorApi({
        [`POST ${C}/turns`]: {
          status: 409,
          body: errorBody("CONVERSATION_CLOSED", "This conversation has ended."),
        },
      }),
    );
    say(await startScenarioA(), "Are you still there?");

    expect(await screen.findByRole("alert")).toHaveTextContent("This call has already ended.");
    expect(screen.queryByLabelText("Caller says")).not.toBeInTheDocument();
    expect(screen.getByText(/The call has ended in state/)).toBeInTheDocument();
  });

  it("returns to the sign-in screen with the reason on 401", async () => {
    renderSimulator(
      simulatorApi({
        [`POST ${C}/turns`]: {
          status: 401,
          body: errorBody("AUTH_INVALID", "The access token has expired."),
        },
      }),
    );
    say(await startScenarioA(), "Hello?");

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "The API rejected the session (AUTH_INVALID): The access token has expired.",
    );
  });

  it("shows a scenario loading error with a retry", async () => {
    renderSimulator(
      simulatorApi({
        "GET /api/v1/scenarios": { status: 503, body: errorBody("PROVIDER_UNAVAILABLE", "Down.") },
      }),
    );
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Scenarios could not be loaded.");
    expect(within(alert).getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});
