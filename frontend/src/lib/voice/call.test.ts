// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import { describe, expect, it, vi } from "vitest";

import { createApiClient } from "@/lib/api/client";
import { CONVERSATION_ID, conversation, makeToken, scenario } from "@/test/fixtures";
import { errorBody, fakeApi, type Route } from "@/test/render";
import {
  FakeClipOutput,
  READY_CREATED,
  fakeVoiceEnvironment,
  latency,
} from "@/test/voice-fakes";

import { VoiceCall } from "./call";

const C = `/api/v1/conversations/${CONVERSATION_ID}`;
const TOKEN = makeToken();
const TICKET = "tkt_0123456789abcdefghijklmnop";

function setup(overrides: Record<string, Route | { status: number; body?: unknown }> = {}) {
  let ticketCount = 0;
  const api = fakeApi({
    "POST /api/v1/conversations": { status: 201, body: conversation() },
    [`POST ${C}/ws-ticket`]: () => ({
      status: 200,
      body: { ticket: `${TICKET}-${++ticketCount}`, expires_in: 60 },
    }),
    "GET /api/v1/audio/clips/a-01": { status: 200, body: { fake: "wav" } },
    "GET /api/v1/audio/clips/a-02": { status: 200, body: { fake: "wav" } },
    [`POST ${C}/end`]: { status: 200, body: conversation({ state: "ABANDONED" }) },
    ...overrides,
  });
  const onUnauthorized = vi.fn();
  const client = createApiClient({
    baseUrl: "http://api.test",
    getToken: () => TOKEN,
    fetchImpl: api.fetchImpl,
    onUnauthorized,
  });
  const env = fakeVoiceEnvironment();
  const clips = new FakeClipOutput();
  const call = new VoiceCall({ ...env, api: client, apiBaseUrl: "http://api.test", clipOutput: clips });
  return { api, env, clips, call, onUnauthorized };
}

/** Lets pending promise callbacks (fake fetch, clip playback) run. */
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

async function startedCall() {
  const parts = setup();
  await parts.call.start(scenario());
  const socket = parts.env.socket();
  socket.open();
  socket.message(READY_CREATED);
  socket.message({ type: "state", state: "GREETING", previous: "CREATED", path: ["GREETING"] });
  socket.message({ type: "assistant.text", turn_seq: 1, text: "Hello! Welcome to BrightSmile." });
  socket.audio(1, [100, 200, 300]);
  socket.message({ type: "assistant.audio_end", turn_seq: 1 });
  socket.message(latency(1, { tts_first_byte_ms: 1 }));
  return { ...parts, socket };
}

describe("VoiceCall", () => {
  it("creates the conversation, gets a ticket and connects without the token in the URL", async () => {
    const { api, env, call } = setup();
    await call.start(scenario());

    expect(api.requests.map((r) => `${r.method} ${r.path}`)).toEqual([
      "POST /api/v1/conversations",
      `POST ${C}/ws-ticket`,
    ]);
    expect(api.requests.every((r) => r.headers.get("Authorization") === `Bearer ${TOKEN}`)).toBe(true);
    const socket = env.socket();
    expect(socket.url).toBe(
      `ws://api.test/api/v1/ws/conversations/${CONVERSATION_ID}?ticket=${TICKET}-1`,
    );
    expect(socket.url).not.toContain(TOKEN);
    expect(socket.url).not.toContain(TOKEN.split(".")[1]);
    expect(socket.url).not.toMatch(/token|authorization|bearer/i);
    expect(call.getSnapshot().phase).toBe("connecting");
  });

  it("creates and resumes the AudioContext synchronously inside start()", () => {
    const { env, call } = setup();
    void call.start(scenario());
    // Before any await resolved: the gesture-bound work is already done.
    expect(env.contexts).toHaveLength(1);
    expect(env.context().resumeCalls).toBe(1);
  });

  it("sends start once the server is ready in CREATED and plays the greeting", async () => {
    const { socket, env, call } = await startedCall();
    expect(socket.commands).toEqual(["start"]);
    const state = call.getSnapshot();
    expect(state).toMatchObject({ phase: "live", state: "GREETING", pending: null });
    expect(state.lines).toEqual([{ seq: 1, speaker: "receptionist", text: "Hello! Welcome to BrightSmile." }]);
    expect(env.context().sources).toHaveLength(1);
    expect(state.playing).toBe(true);
    expect(call.playbackStats).toMatchObject({ scheduledBuffers: 1, droppedFrames: 0 });
  });

  it("does not send start when reconnecting into a started call", async () => {
    const { env, call } = setup();
    await call.start(scenario());
    env.socket().open();
    env.socket().message({ ...READY_CREATED, state: "CONTACT_DETAILS" });
    expect(env.socket().commands).toEqual([]);
    expect(call.getSnapshot().state).toBe("CONTACT_DETAILS");
  });

  it("plays the caller clip from a blob fetched with the bearer token, then revokes it", async () => {
    const { socket, api, env, clips, call } = await startedCall();
    env.context().sources[0].finish();
    call.nextLine();
    expect(socket.commands).toEqual(["start", "next_clip"]);

    socket.message({ type: "clip", clip_id: "a-01", url: "/api/v1/audio/clips/a-01", duration_ms: 3000 });
    await flush();
    const clipRequest = api.requests.at(-1)!;
    expect(clipRequest.path).toBe("/api/v1/audio/clips/a-01");
    expect(clipRequest.headers.get("Authorization")).toBe(`Bearer ${TOKEN}`);
    expect(clips.played).toEqual(["blob:fake/1"]);
    expect(call.getSnapshot().clipPlaying).toBe(true);

    socket.message({ type: "transcript.interim", text: "Hi! I'd" });
    expect(call.getSnapshot().interim).toBe("Hi! I'd");
    clips.finish();
    expect(env.revokedUrls).toEqual(["blob:fake/1"]);
    expect(call.getSnapshot().clipPlaying).toBe(false);
  });

  it("drops receptionist frames of a turn older than the latest assistant.text", async () => {
    const { socket, env, call } = await startedCall();
    env.context().sources[0].finish();
    call.nextLine();
    socket.message({ type: "utterance.final", turn_seq: 2, text: "Hi!" });
    socket.message({ type: "assistant.text", turn_seq: 3, text: "Could I have your name?" });
    socket.audio(1, [1, 2, 3]); // late frame of the greeting
    socket.audio(3, [1, 2, 3]);
    expect(env.context().sources).toHaveLength(2); // greeting + turn 3 only
    expect(call.playbackStats).toMatchObject({ scheduledBuffers: 2, droppedFrames: 1 });
  });

  it("barge-in: Next caller line while the receptionist speaks stops playback first", async () => {
    const { socket, env, call } = await startedCall();
    const greeting = env.context().sources[0];
    expect(call.getSnapshot().playing).toBe(true);

    call.nextLine();
    expect(greeting.stopped).toBe(true);
    expect(call.getSnapshot()).toMatchObject({ playing: false, bargeIns: [1], pending: "next_clip" });
    expect(socket.commands).toEqual(["start", "next_clip"]);

    socket.audio(1, [1, 2]); // still in flight from the server
    expect(env.context().sources).toHaveLength(1);
    socket.message({ type: "assistant.audio_cancelled", turn_seq: 1 });
    expect(call.getSnapshot().cancelledTurns).toEqual([1]);
  });

  it("stops scheduled audio on assistant.audio_cancelled", async () => {
    const { socket, env, call } = await startedCall();
    socket.message({ type: "assistant.audio_cancelled", turn_seq: 1 });
    expect(env.context().active).toHaveLength(0);
    expect(call.getSnapshot().playing).toBe(false);
  });

  it("hang-up sends end, silences audio and the clip, and ends on closed", async () => {
    const { socket, env, clips, call } = await startedCall();
    env.context().sources[0].finish();
    call.nextLine();
    socket.message({ type: "clip", clip_id: "a-01", url: "/api/v1/audio/clips/a-01", duration_ms: 3000 });
    await flush();
    expect(clips.played).toHaveLength(1);
    await call.hangUp();
    expect(socket.commands).toEqual(["start", "next_clip", "end"]);
    expect(clips.stops).toBe(1);
    expect(env.revokedUrls).toEqual(["blob:fake/1"]);
    expect(env.context().active).toHaveLength(0);
    expect(call.getSnapshot().phase).toBe("ending");
    socket.message({ type: "state", state: "ABANDONED", previous: "GREETING", path: ["ABANDONED"] });
    socket.message({ type: "closed", state: "ABANDONED" });
    socket.serverClose(1000);
    expect(call.getSnapshot()).toMatchObject({ phase: "ended", closedState: "ABANDONED" });
  });

  it("an unexpected close offers reconnect with a new ticket", async () => {
    const { socket, env, api, call } = await startedCall();
    socket.serverClose(1006);
    expect(call.getSnapshot()).toMatchObject({ phase: "disconnected", lastClose: { code: 1006 } });
    expect(env.context().active).toHaveLength(0);

    await call.reconnect();
    expect(env.sockets).toHaveLength(2);
    expect(env.socket().url).toContain(`ticket=${TICKET}-2`);
    expect(api.requests.filter((r) => r.path.endsWith("/ws-ticket"))).toHaveLength(2);

    // Events from the old socket are ignored.
    socket.message({ type: "assistant.text", turn_seq: 9, text: "stale" });
    expect(call.getSnapshot().lines).toHaveLength(1);

    env.socket().open();
    env.socket().message({ ...READY_CREATED, state: "GREETING" });
    expect(call.getSnapshot()).toMatchObject({ phase: "live", connections: 2 });
    expect(env.socket().commands).toEqual([]);
  });

  it("hangs up over REST when the socket is gone", async () => {
    const { socket, api, call } = await startedCall();
    socket.serverClose(1006);
    await call.hangUp();
    expect(api.requests.at(-1)?.path).toBe(`${C}/end`);
    expect(call.getSnapshot()).toMatchObject({ phase: "ended", closedState: "ABANDONED" });
  });

  it("shows a 403 from conversation creation and stays on scenario choice", async () => {
    const { call, env } = setup({
      "POST /api/v1/conversations": {
        status: 403,
        body: errorBody("FORBIDDEN", "Your role does not allow this action."),
      },
    });
    await call.start(scenario());
    expect(call.getSnapshot().phase).toBe("idle");
    expect(call.getSnapshot().errors[0]).toMatchObject({ code: "FORBIDDEN", status: 403 });
    expect(env.sockets).toHaveLength(0);
  });

  it("reports a 401 to the session (sign-in) and shows it", async () => {
    const { call, onUnauthorized } = setup({
      [`POST ${C}/ws-ticket`]: { status: 401, body: errorBody("AUTH_INVALID", "Expired.") },
    });
    await call.start(scenario());
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
    expect(call.getSnapshot().errors[0]).toMatchObject({ code: "AUTH_INVALID", status: 401 });
  });

  it("reports a clip that cannot be fetched or played", async () => {
    const { socket, env, clips, call } = await startedCall();
    env.context().sources[0].finish();
    call.nextLine();
    socket.message({ type: "clip", clip_id: "x-99", url: "https://evil.example.com/x", duration_ms: 1 });
    await flush();
    expect(call.getSnapshot().errors.at(-1)?.code).toBe("UNEXPECTED_RESPONSE");

    clips.failWith = new Error("play() was blocked");
    socket.message({ type: "clip", clip_id: "a-02", url: "/api/v1/audio/clips/a-02", duration_ms: 1 });
    await flush();
    expect(call.getSnapshot().errors.at(-1)).toMatchObject({
      code: "CLIP_PLAYBACK_FAILED",
      message: "The caller clip could not be played: play() was blocked",
    });
    expect(env.revokedUrls).toEqual(env.createdUrls);
  });

  it("reports malformed server messages and frames, and ignores unknown types", async () => {
    const { socket, call } = await startedCall();
    socket.text("{not json");
    socket.message({ type: "latency", turn_seq: 3, stt_ms: "fast" });
    socket.message({ type: "future.feature", x: 1 });
    socket.text("x");
    expect(call.getSnapshot().errors.map((error) => error.code)).toEqual([
      "INVALID_SERVER_MESSAGE",
      "INVALID_SERVER_MESSAGE",
      "INVALID_SERVER_MESSAGE",
    ]);
    expect(call.getSnapshot().ignoredMessageTypes).toEqual(["future.feature"]);
  });

  it("reset and dispose close the socket and the audio context", async () => {
    const { socket, env, call } = await startedCall();
    call.dispose();
    expect(socket.closedByClient).toEqual({ code: 1000, reason: "client closed" });
    await flush();
    expect(env.context().state).toBe("closed");
    call.reset();
    expect(call.getSnapshot().phase).toBe("idle");
  });
});
