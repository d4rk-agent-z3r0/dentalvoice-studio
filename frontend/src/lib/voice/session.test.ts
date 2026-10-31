// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import { describe, expect, it } from "vitest";

import type { ConversationState } from "@/lib/api/types";
import { conversation, scenario } from "@/test/fixtures";

import type { ServerMessage } from "./protocol";
import {
  INITIAL_STATE,
  activity,
  canAdvance,
  canHangUp,
  receptionistSpeaking,
  voiceReducer,
  type VoiceAction,
  type VoiceCallState,
} from "./session";

const server = (message: ServerMessage): VoiceAction => ({ type: "server", message });

function run(actions: VoiceAction[], from: VoiceCallState = INITIAL_STATE): VoiceCallState {
  return actions.reduce(voiceReducer, from);
}

const READY: ServerMessage = {
  type: "ready",
  state: "CREATED",
  audio: { sample_rate: 24000, encoding: "linear16", channels: 1 },
};

function connected(): VoiceCallState {
  return run([
    { type: "prepare", scenario: scenario() },
    { type: "created", conversation: conversation() },
    { type: "connecting" },
    { type: "socket_open" },
    server(READY),
  ]);
}

function callerTurn(
  caller: number,
  text: string,
  reply: string,
  previous: ConversationState,
  path: ConversationState[],
): VoiceAction[] {
  const receptionist = caller + 1;
  return [
    { type: "command", command: { type: "next_clip" } },
    server({ type: "clip", clip_id: `a-0${caller}`, url: `/api/v1/audio/clips/a-0${caller}`, duration_ms: 2000 }),
    server({ type: "transcript.interim", text: text.split(" ").slice(0, 2).join(" ") }),
    server({ type: "utterance.final", turn_seq: caller, text }),
    ...(path.length > 0 ? [server({ type: "state", state: path.at(-1)!, previous, path })] : []),
    server({ type: "assistant.text", turn_seq: receptionist, text: reply }),
    server({ type: "intake", missing_fields: [], rejected_fields: {}, corrected_fields: [] }),
    server({ type: "assistant.audio_end", turn_seq: receptionist }),
    server({ type: "latency", turn_seq: receptionist, stt_ms: 40, llm_ms: 2, tts_first_byte_ms: 1, total_ms: 45 }),
  ];
}

describe("voiceReducer", () => {
  it("walks a whole call from scenario choice to COMPLETED", () => {
    let state = run([{ type: "prepare", scenario: scenario() }]);
    expect(state.phase).toBe("preparing");
    expect(activity(state)).toBe("connecting");

    state = run([{ type: "created", conversation: conversation() }, { type: "connecting" }], state);
    expect(state.phase).toBe("connecting");
    expect(canHangUp(state)).toBe(true);

    state = run([{ type: "socket_open" }, server(READY)], state);
    expect(state).toMatchObject({ phase: "live", state: "CREATED", connections: 1 });
    expect(state.audio).toEqual(READY.type === "ready" ? READY.audio : null);
    expect(canAdvance(state)).toBe(false); // not started yet

    // Greeting.
    state = run(
      [
        { type: "command", command: { type: "start" } },
        server({ type: "state", state: "GREETING", previous: "CREATED", path: ["GREETING"] }),
        server({ type: "assistant.text", turn_seq: 1, text: "Hello! Welcome to BrightSmile." }),
        server({ type: "intake", missing_fields: ["first_name"], rejected_fields: {}, corrected_fields: [] }),
      ],
      state,
    );
    expect(state.pending).toBeNull();
    expect(state.streamingTurn).toBe(1);
    expect(receptionistSpeaking(state)).toBe(true);
    expect(activity(state)).toBe("receptionist_speaking");
    state = run(
      [server({ type: "assistant.audio_end", turn_seq: 1 }), server({ type: "latency", turn_seq: 1, stt_ms: null, llm_ms: null, tts_first_byte_ms: 1, total_ms: null })],
      state,
    );
    expect(activity(state)).toBe("your_turn");
    expect(canAdvance(state)).toBe(true);
    expect(state.timeline).toEqual([{ from: "CREATED", to: "GREETING", turnSeq: 1 }]);

    // First caller turn: interim is provisional, then replaced by the committed utterance.
    state = run([{ type: "command", command: { type: "next_clip" } }], state);
    expect(canAdvance(state)).toBe(false);
    state = run(
      [
        server({ type: "clip", clip_id: "a-01", url: "/api/v1/audio/clips/a-01", duration_ms: 4000 }),
        { type: "clip_playback", playing: true },
        server({ type: "transcript.interim", text: "Hi! I'd like" }),
      ],
      state,
    );
    expect(state.interim).toBe("Hi! I'd like");
    expect(state.clip).toEqual({ clipId: "a-01", durationMs: 4000 });
    expect(activity(state)).toBe("caller_speaking");
    state = run([{ type: "clip_playback", playing: false }], state);
    expect(activity(state)).toBe("thinking");
    state = run(
      [
        server({ type: "utterance.final", turn_seq: 2, text: "Hi! I'd like to book a teeth cleaning, please." }),
        server({ type: "state", state: "IDENTITY_COLLECTION", previous: "GREETING", path: ["INTRODUCTION", "IDENTITY_COLLECTION"] }),
        server({ type: "assistant.text", turn_seq: 3, text: "Could I have your name?" }),
      ],
      state,
    );
    expect(state.interim).toBeNull();
    expect(state.lines.map((line) => [line.speaker, line.seq])).toEqual([
      ["receptionist", 1],
      ["caller", 2],
      ["receptionist", 3],
    ]);
    expect(state.timeline.slice(1)).toEqual([
      { from: "GREETING", to: "INTRODUCTION", turnSeq: 3 },
      { from: "INTRODUCTION", to: "IDENTITY_COLLECTION", turnSeq: 3 },
    ]);

    // Rejections and corrections are reported per turn and kept in the call history.
    state = run(
      [
        server({
          type: "intake",
          missing_fields: ["email"],
          rejected_fields: { email: "Only reserved example domains are allowed." },
          corrected_fields: ["last_name"],
        }),
        server({ type: "assistant.audio_end", turn_seq: 3 }),
        server({ type: "latency", turn_seq: 3, stt_ms: 41, llm_ms: 3, tts_first_byte_ms: 0, total_ms: 46 }),
      ],
      state,
    );
    expect(state.intake).toEqual({
      turnSeq: 3,
      missing: ["email"],
      rejected: { email: "Only reserved example domains are allowed." },
      corrected: ["last_name"],
    });
    expect(state.intakeHistory).toHaveLength(1);
    expect(state.latencies).toEqual([
      { turnSeq: 1, stt_ms: null, llm_ms: null, tts_first_byte_ms: 1, total_ms: null },
      { turnSeq: 3, stt_ms: 41, llm_ms: 3, tts_first_byte_ms: 0, total_ms: 46 },
    ]);

    // Final turn and close.
    state = run(
      [
        ...callerTurn(4, "Yes, please go ahead and confirm it.", "All set.", "CONFIRMATION_PENDING", ["COMPLETED"]),
        server({ type: "closed", state: "COMPLETED" }),
      ],
      state,
    );
    expect(state).toMatchObject({ phase: "ended", state: "COMPLETED", closedState: "COMPLETED" });
    expect(canAdvance(state)).toBe(false);
    expect(canHangUp(state)).toBe(false);
    expect(activity(state)).toBe("ended");

    // The server's normal close after `closed` is not a disconnection.
    expect(voiceReducer(state, { type: "socket_closed", code: 1000, reason: "" }).phase).toBe("ended");
  });

  it("records barge-in and cancelled speech once per turn", () => {
    let state = run([
      server({ type: "assistant.text", turn_seq: 3, text: "Could I have your name?" }),
      { type: "playback", playing: true },
    ], connected());
    expect(receptionistSpeaking(state)).toBe(true);
    state = run(
      [
        { type: "barge_in", turnSeq: 3 },
        { type: "barge_in", turnSeq: 3 },
        { type: "playback", playing: false },
        server({ type: "assistant.audio_cancelled", turn_seq: 3 }),
        server({ type: "assistant.audio_cancelled", turn_seq: 3 }),
      ],
      state,
    );
    expect(state.bargeIns).toEqual([3]);
    expect(state.cancelledTurns).toEqual([3]);
    expect(state.streamingTurn).toBeNull();
    expect(receptionistSpeaking(state)).toBe(false);
  });

  it("keeps every server error with its code and provider, and frees the pending command", () => {
    let state = run([{ type: "command", command: { type: "next_clip" } }], connected());
    state = run(
      [server({ type: "error", code: "PROVIDER_ERROR", message: "A speech or language provider failed.", provider: "deepgram" })],
      state,
    );
    state = run([server({ type: "error", code: "NO_SPEECH", message: "No speech was recognised in that clip.", provider: null })], state);
    expect(state.errors.map((error) => [error.id, error.code, error.provider])).toEqual([
      [1, "PROVIDER_ERROR", "deepgram"],
      [2, "NO_SPEECH", null],
    ]);
    expect(state.pending).toBeNull();
    expect(state.lines).toEqual([]); // nothing invented in place of a reply
  });

  it("keeps the pending command on BUSY", () => {
    const state = run(
      [
        { type: "command", command: { type: "next_clip" } },
        server({ type: "error", code: "BUSY", message: "The previous turn is still being processed.", provider: null }),
      ],
      connected(),
    );
    expect(state.pending).toBe("next_clip");
    expect(state.errors).toHaveLength(1);
  });

  it("treats CONVERSATION_CLOSED as the end of the call", () => {
    const state = run(
      [server({ type: "error", code: "CONVERSATION_CLOSED", message: "This conversation has ended.", provider: null })],
      connected(),
    );
    expect(state.phase).toBe("ended");
  });

  it("marks an unexpected close as disconnected and clears in-flight work", () => {
    let state = run(
      [
        { type: "command", command: { type: "next_clip" } },
        server({ type: "clip", clip_id: "a-02", url: "/api/v1/audio/clips/a-02", duration_ms: 2000 }),
        server({ type: "transcript.interim", text: "Sure" }),
      ],
      connected(),
    );
    state = voiceReducer(state, { type: "socket_closed", code: 1006, reason: "" });
    expect(state).toMatchObject({
      phase: "disconnected",
      lastClose: { code: 1006, reason: "" },
      pending: null,
      clip: null,
      interim: null,
    });
    expect(activity(state)).toBe("disconnected");
    expect(canHangUp(state)).toBe(true);
    state = run([{ type: "connecting" }, { type: "socket_open" }, server({ ...READY, state: "IDENTITY_COLLECTION" } as ServerMessage)], state);
    expect(state).toMatchObject({ phase: "live", connections: 2, lastClose: null });
  });

  it("a ready in a terminal state ends the call", () => {
    const state = run([server({ ...READY, state: "ABANDONED" } as ServerMessage)], connected());
    expect(state).toMatchObject({ phase: "ended", closedState: "ABANDONED" });
  });

  it("hang-up moves to ending until the server confirms", () => {
    const state = run([{ type: "command", command: { type: "end" } }], connected());
    expect(state.phase).toBe("ending");
    const ended = run(
      [
        server({ type: "state", state: "ABANDONED", previous: "GREETING", path: ["ABANDONED"] }),
        server({ type: "closed", state: "ABANDONED" }),
      ],
      state,
    );
    expect(ended).toMatchObject({ phase: "ended", closedState: "ABANDONED" });
  });

  it("returns to scenario choice when the conversation could not be created", () => {
    const state = run([
      { type: "prepare", scenario: scenario() },
      { type: "failure", error: { source: "api", code: "FORBIDDEN", message: "No.", status: 403 } },
    ]);
    expect(state.phase).toBe("idle");
    expect(state.errors[0]).toMatchObject({ code: "FORBIDDEN", status: 403 });
  });

  it("collects unknown message types once without changing the call", () => {
    const before = connected();
    const state = run(
      [
        { type: "unknown_message", messageType: "assistant.mood" },
        { type: "unknown_message", messageType: "assistant.mood" },
      ],
      before,
    );
    expect(state.ignoredMessageTypes).toEqual(["assistant.mood"]);
    expect({ ...state, ignoredMessageTypes: [] }).toEqual(before);
  });

  it("resets to the initial state", () => {
    expect(voiceReducer(connected(), { type: "reset" })).toBe(INITIAL_STATE);
  });
});
