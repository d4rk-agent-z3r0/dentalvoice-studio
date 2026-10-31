// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import { act, fireEvent, screen, within } from "@testing-library/react";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RequireSession } from "@/components/auth/RequireSession";
import { TEXT_TURN_PROBE_ID } from "@/lib/api/client";
import { CONVERSATION_ID, conversation, makeToken, scenario } from "@/test/fixtures";
import { errorBody, fakeApi, renderWithProviders, signedInStore, type Route } from "@/test/render";
import {
  FakeClipOutput,
  READY_CREATED,
  fakeVoiceEnvironment,
  latency,
  type FakeVoiceEnvironment,
} from "@/test/voice-fakes";

import { SimulatorWorkspace } from "./SimulatorWorkspace";
import { TEXT_MODE_LABEL } from "./TextSimulator";

const C = `/api/v1/conversations/${CONVERSATION_ID}`;
const PROBE = `POST /api/v1/conversations/${TEXT_TURN_PROBE_ID}/turns`;
const TICKET = "tkt_0123456789abcdefghijklmnop";

function voiceApi(overrides: Record<string, Route | { status: number; body?: unknown }> = {}) {
  return fakeApi({
    "GET /api/v1/scenarios": {
      status: 200,
      body: [
        scenario({ clips: ["a-01", "a-02"] }),
        scenario({ id: "s-e", code: "E", title: "Urgent symptoms: escalation", objective: "Escalate.", clips: ["e-01"] }),
      ],
    },
    [PROBE]: { status: 403, body: errorBody("FORBIDDEN", "Typed turns are disabled in this environment.") },
    "POST /api/v1/conversations": { status: 201, body: conversation() },
    [`POST ${C}/ws-ticket`]: { status: 200, body: { ticket: TICKET, expires_in: 60 } },
    "GET /api/v1/audio/clips/a-01": { status: 200, body: { fake: "wav" } },
    "GET /api/v1/audio/clips/a-02": { status: 200, body: { fake: "wav" } },
    ...overrides,
  });
}

interface Harness {
  api: ReturnType<typeof voiceApi>;
  env: FakeVoiceEnvironment;
  clips: FakeClipOutput;
}

function renderVoice(api = voiceApi(), store = signedInStore()): Harness {
  const env = fakeVoiceEnvironment();
  const clips = new FakeClipOutput();
  renderWithProviders(
    <RequireSession>
      <SimulatorWorkspace environment={env} clipOutput={clips} />
    </RequireSession>,
    { fetchImpl: api.fetchImpl, store },
  );
  return { api, env, clips };
}

/** Server messages arrive outside React's event handlers. */
function serverSays(env: FakeVoiceEnvironment, ...messages: Record<string, unknown>[]) {
  act(() => messages.forEach((message) => env.socket().message(message)));
}

async function startCall(h: Harness, code: "A" | "E" = "A") {
  fireEvent.click(await screen.findByRole("radio", { name: new RegExp(`^${code} · `) }));
  fireEvent.click(screen.getByRole("button", { name: "Start call" }));
  await screen.findByRole("heading", { name: /· / , level: 2 });
  await vi.waitFor(() => expect(h.env.sockets).toHaveLength(1));
  act(() => h.env.socket().open());
  serverSays(h.env, READY_CREATED);
  serverSays(
    h.env,
    { type: "state", state: "GREETING", previous: "CREATED", path: ["GREETING"] },
    { type: "assistant.text", turn_seq: 1, text: "Hello! Welcome to BrightSmile Dental Studio." },
    { type: "intake", missing_fields: ["first_name", "last_name"], rejected_fields: {}, corrected_fields: [] },
  );
  act(() => h.env.socket().audio(1, [10, 20, 30, 40]));
  serverSays(h.env, { type: "assistant.audio_end", turn_seq: 1 }, latency(1, { tts_first_byte_ms: 0 }));
}

function finishPlayback(env: FakeVoiceEnvironment) {
  act(() => env.context().sources.forEach((source) => source.finish()));
}

let getUserMedia: ReturnType<typeof vi.fn>;

beforeEach(() => {
  // jsdom has no mediaDevices; install a spy only for this file's tests and remove it afterwards.
  getUserMedia = vi.fn();
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia },
  });
});

afterEach(() => {
  Reflect.deleteProperty(navigator, "mediaDevices");
});

describe("Voice simulator", () => {
  it("is the default mode; text mode is a secondary tab that is not probed until opened", async () => {
    const h = renderVoice();
    expect(await screen.findAllByRole("radio")).toHaveLength(2);
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((tab) => tab.textContent)).toEqual(["Voice call", "Text mode (development)"]);
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText(/Your microphone is\s+never used/)).toBeInTheDocument();
    expect(h.api.requests.map((r) => `${r.method} ${r.path}`)).toEqual(["GET /api/v1/scenarios"]);
  });

  it("explains that text mode is unavailable when the backend refuses typed turns", async () => {
    const h = renderVoice();
    fireEvent.click(await screen.findByRole("tab", { name: "Text mode (development)" }));
    expect(await screen.findByText("Text mode is not available on this backend")).toBeInTheDocument();
    expect(h.api.requests.some((r) => `${r.method} ${r.path}` === PROBE)).toBe(true);
    expect(screen.queryByText(TEXT_MODE_LABEL)).not.toBeInTheDocument();
  });

  it("offers the text form when the backend accepts typed turns, with keyboard tab navigation", async () => {
    renderVoice(voiceApi({ [PROBE]: { status: 404, body: errorBody("NOT_FOUND", "Conversation not found.") } }));
    await screen.findAllByRole("radio");
    const tabs = screen.getAllByRole("tab");
    fireEvent.keyDown(tabs[0], { key: "ArrowRight" });
    expect(tabs[1]).toHaveAttribute("aria-selected", "true");
    expect(tabs[1]).toHaveFocus();
    expect(await screen.findByText(TEXT_MODE_LABEL)).toBeInTheDocument();
    fireEvent.keyDown(tabs[1], { key: "ArrowLeft" });
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    expect(tabs[0]).toHaveFocus();
  });

  it("runs a call: greeting, caller clip, interim, committed utterance, reply, state, intake, latency", async () => {
    const h = renderVoice();
    await startCall(h);

    expect(h.env.socket().commands).toEqual(["start"]);
    expect(h.env.socket().url).toBe(
      `ws://localhost:8000/api/v1/ws/conversations/${CONVERSATION_ID}?ticket=${TICKET}`,
    );
    const transcript = screen.getByRole("list", { name: "Call transcript" });
    expect(transcript).toHaveTextContent("Hello! Welcome to BrightSmile Dental Studio.");
    const status = screen.getByRole("complementary", { name: "Call status" });
    expect(status).toHaveTextContent("Greeting");
    expect(within(status).getByRole("list", { name: "Missing fields" })).toHaveTextContent("First nameLast name");
    // The greeting has no STT or LLM stage: dashes, never 0.
    const greetingRow = screen.getByRole("row", { name: /#1/ });
    expect(within(greetingRow).getAllByRole("cell").map((cell) => cell.textContent)).toEqual(["—", "—", "0 ms", "—"]);
    expect(h.env.context().sources).toHaveLength(1);

    finishPlayback(h.env);
    expect(screen.getByText("Waiting for the next caller line")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next caller line" }));
    expect(h.env.socket().commands).toEqual(["start", "next_clip"]);
    expect(screen.getByRole("button", { name: "Next caller line" })).toBeDisabled();

    serverSays(h.env, { type: "clip", clip_id: "a-01", url: "/api/v1/audio/clips/a-01", duration_ms: 3000 });
    await vi.waitFor(() => expect(h.clips.played).toEqual(["blob:fake/1"]));
    expect(screen.getByText("Caller speaking")).toBeInTheDocument();
    serverSays(h.env, { type: "transcript.interim", text: "Hi! I'd like to" });
    const provisional = screen.getByText("Hi! I'd like to").closest("li");
    expect(provisional).toHaveAttribute("data-provisional", "true");
    expect(provisional).toHaveTextContent("transcribing (provisional)");

    act(() => h.clips.finish());
    expect(h.env.revokedUrls).toEqual(["blob:fake/1"]);
    serverSays(
      h.env,
      { type: "utterance.final", turn_seq: 2, text: "Hi! I'd like to book a teeth cleaning, please." },
      { type: "state", state: "IDENTITY_COLLECTION", previous: "GREETING", path: ["INTRODUCTION", "IDENTITY_COLLECTION"] },
      { type: "assistant.text", turn_seq: 3, text: "Could I have your first and last name?" },
      {
        type: "intake",
        missing_fields: ["email"],
        rejected_fields: { email: "Only reserved example domains are allowed." },
        corrected_fields: ["last_name"],
      },
      { type: "assistant.audio_end", turn_seq: 3 },
      latency(3, { stt_ms: 41, llm_ms: 3, tts_first_byte_ms: 1, total_ms: 46 }),
    );

    expect(screen.queryByText("Hi! I'd like to")).not.toBeInTheDocument();
    const items = within(transcript).getAllByRole("listitem");
    expect(items.map((item) => item.dataset.speaker)).toEqual(["receptionist", "caller", "receptionist"]);
    expect(items[1]).toHaveTextContent("Hi! I'd like to book a teeth cleaning, please.");
    const timeline = within(status).getByRole("list", { name: "State timeline" });
    expect(timeline).toHaveTextContent("Introduction from Greeting · turn #3");
    expect(timeline).toHaveTextContent("Identity from Introduction · turn #3");
    expect(status).toHaveTextContent("Email: Only reserved example domains are allowed.");
    expect(status).toHaveTextContent("Corrected in the last turnLast name");
    const turnRow = screen.getByRole("row", { name: /#3/ });
    expect(within(turnRow).getAllByRole("cell").map((cell) => cell.textContent)).toEqual([
      "41 ms",
      "3 ms",
      "1 ms",
      "46 ms",
    ]);
    // The latest receptionist line is announced politely.
    expect(document.querySelector('[aria-live="polite"]')).toHaveTextContent(
      "Receptionist: Could I have your first and last name?",
    );
  });

  it("barge-in: Next caller line while the receptionist speaks cancels playback", async () => {
    const h = renderVoice();
    await startCall(h);
    const greeting = h.env.context().sources[0];
    expect(screen.getByText("Receptionist speaking")).toBeInTheDocument();
    expect(screen.getByText(/the next line interrupts \(barge-in\)/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Next caller line" }));
    expect(greeting.stopped).toBe(true);
    expect(h.env.context().active).toHaveLength(0);
    act(() => h.env.socket().audio(1, [1, 2])); // in flight before the server cancelled
    expect(h.env.context().sources).toHaveLength(1);
    serverSays(h.env, { type: "assistant.audio_cancelled", turn_seq: 1 });
    expect(screen.getByText("Speech interrupted")).toBeInTheDocument();
  });

  it("ends with a summary that links to the conversation", async () => {
    const h = renderVoice();
    await startCall(h, "E");
    finishPlayback(h.env);
    fireEvent.click(screen.getByRole("button", { name: "Next caller line" }));
    serverSays(
      h.env,
      { type: "utterance.final", turn_seq: 2, text: "My jaw is really swollen, I have a fever." },
      { type: "state", state: "ESCALATED", previous: "GREETING", path: ["INTRODUCTION", "ESCALATED"] },
      { type: "assistant.text", turn_seq: 3, text: "I'm flagging this for our clinical team right away." },
      { type: "intake", missing_fields: [], rejected_fields: {}, corrected_fields: [] },
      { type: "assistant.audio_end", turn_seq: 3 },
      latency(3, { stt_ms: 12, llm_ms: 2, tts_first_byte_ms: 0, total_ms: 15 }),
      { type: "closed", state: "ESCALATED" },
    );
    act(() => h.env.socket().serverClose(1000));

    const summary = screen.getByRole("region", { name: "Call summary" });
    expect(summary).toHaveTextContent("Final stateEscalated");
    expect(summary).toHaveTextContent("Caller lines1");
    expect(within(summary).getByRole("link", { name: "View conversation details" })).toHaveAttribute(
      "href",
      `/conversations/${CONVERSATION_ID}`,
    );
    expect(screen.queryByRole("button", { name: "Next caller line" })).not.toBeInTheDocument();
    expect(screen.queryByText(/connection closed unexpectedly/)).not.toBeInTheDocument();

    fireEvent.click(within(summary).getByRole("button", { name: "Start another call" }));
    expect(await screen.findAllByRole("radio")).toHaveLength(2);
  });

  it("hang up sends end and shows the abandoned call", async () => {
    const h = renderVoice();
    await startCall(h);
    fireEvent.click(screen.getByRole("button", { name: "Hang up" }));
    expect(h.env.socket().commands).toEqual(["start", "end"]);
    expect(h.env.context().active).toHaveLength(0);
    serverSays(
      h.env,
      { type: "state", state: "ABANDONED", previous: "GREETING", path: ["ABANDONED"] },
      { type: "closed", state: "ABANDONED" },
    );
    expect(screen.getByRole("region", { name: "Call summary" })).toHaveTextContent("Abandoned");
  });

  it("shows every server error with code and provider; nothing replaces the reply", async () => {
    const h = renderVoice();
    await startCall(h);
    finishPlayback(h.env);
    fireEvent.click(screen.getByRole("button", { name: "Next caller line" }));
    serverSays(h.env, {
      type: "error",
      code: "PROVIDER_ERROR",
      message: "A speech or language provider failed.",
      provider: "deepgram",
    });
    const alert = screen.getByRole("alert", { name: "Call errors" });
    expect(alert).toHaveTextContent("A speech or language provider failed. Nothing was substituted.");
    expect(alert).toHaveTextContent("PROVIDER_ERROR · provider deepgram");
    expect(within(screen.getByRole("list", { name: "Call transcript" })).getAllByRole("listitem")).toHaveLength(1);
    // The call can continue: the command is no longer pending.
    expect(screen.getByRole("button", { name: "Next caller line" })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "Next caller line" }));
    serverSays(h.env, { type: "error", code: "NO_MORE_CLIPS", message: "This scenario has no more caller clips." });
    expect(within(alert).getAllByRole("listitem")).toHaveLength(2);
    expect(alert).toHaveTextContent("NO_MORE_CLIPS");
  });

  it("offers Reconnect after an unexpected close, with a new ticket", async () => {
    const h = renderVoice();
    await startCall(h);
    act(() => h.env.socket().serverClose(1011, "internal error"));
    expect(screen.getByText("The connection closed unexpectedly.")).toBeInTheDocument();
    expect(screen.getByText(/Close code 1011: internal error/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Reconnect" }));
    await vi.waitFor(() => expect(h.env.sockets).toHaveLength(2));
    act(() => h.env.socket().open());
    serverSays(h.env, { ...READY_CREATED, state: "GREETING" });
    expect(h.env.socket().commands).toEqual([]);
    expect(screen.getByRole("button", { name: "Next caller line" })).toBeEnabled();
    expect(h.api.requests.filter((r) => r.path.endsWith("/ws-ticket"))).toHaveLength(2);
  });

  it("does not offer Start call to a viewer", async () => {
    renderVoice(voiceApi(), signedInStore(makeToken({ role: "viewer" })));
    expect(await screen.findAllByRole("radio")).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "Start call" })).not.toBeInTheDocument();
    expect(screen.getByText(/starting a call needs the staff or admin role/)).toBeInTheDocument();
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
  });

  it("explains a 403 when creating the call", async () => {
    const h = renderVoice(
      voiceApi({
        "POST /api/v1/conversations": {
          status: 403,
          body: errorBody("FORBIDDEN", "Your role does not allow this action.", "rid-403"),
        },
      }),
    );
    fireEvent.click(await screen.findByRole("radio", { name: /^A · / }));
    fireEvent.click(screen.getByRole("button", { name: "Start call" }));
    const alert = await screen.findByText("Your role does not allow this action.");
    expect(alert.closest("li")).toHaveTextContent("FORBIDDEN · HTTP 403 · request rid-403");
    expect(screen.getByRole("button", { name: "Start call" })).toBeEnabled();
    expect(h.env.sockets).toHaveLength(0);
  });

  it("returns to sign-in on 401", async () => {
    renderVoice(
      voiceApi({
        [`POST ${C}/ws-ticket`]: { status: 401, body: errorBody("AUTH_INVALID", "The access token has expired.") },
      }),
    );
    fireEvent.click(await screen.findByRole("radio", { name: /^A · / }));
    fireEvent.click(screen.getByRole("button", { name: "Start call" }));
    expect(await screen.findByRole("heading", { name: "Developer sign-in" })).toBeInTheDocument();
  });

  it("never asks for the microphone during a call", async () => {
    const h = renderVoice();
    await startCall(h);
    finishPlayback(h.env);
    fireEvent.click(screen.getByRole("button", { name: "Next caller line" }));
    serverSays(h.env, { type: "clip", clip_id: "a-01", url: "/api/v1/audio/clips/a-01", duration_ms: 3000 });
    await vi.waitFor(() => expect(h.clips.played).toHaveLength(1));
    fireEvent.click(screen.getByRole("button", { name: "Hang up" }));
    expect(getUserMedia).not.toHaveBeenCalled();
  });
});

describe("source code", () => {
  it("never requests microphone access or uploads audio anywhere in the app", () => {
    const root = join(process.cwd(), "src");
    const files = readdirSync(root, { recursive: true, encoding: "utf8" }).filter(
      (file) => /\.(ts|tsx)$/.test(file) && !/\.test\.tsx?$/.test(file),
    );
    expect(files.length).toBeGreaterThan(20);
    for (const file of files) {
      const source = readFileSync(join(root, file), "utf8");
      expect(source, file).not.toMatch(/getUserMedia|mediaDevices|MediaRecorder|getDisplayMedia/);
    }
  });
});
