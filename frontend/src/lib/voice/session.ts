// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
/**
 * The voice call as a pure reducer: every server message and local event is an action, and the
 * state holds exactly what the server reported (no estimates, no invented replies). Framework-free
 * so a whole call can be replayed in a unit test.
 */
import type { ApiError } from "@/lib/api/errors";
import {
  TERMINAL_STATES,
  type Conversation,
  type ConversationState,
  type Scenario,
  type Speaker,
} from "@/lib/api/types";

import type { AudioFormat, ClientCommand, ServerMessage } from "./protocol";

/**
 * - `idle`: choosing a scenario. `preparing`: creating the conversation. `connecting`: getting a
 *   ticket and opening the socket. `live`: socket open. `ending`: hang-up sent.
 * - `ended`: the server reported the call closed. `disconnected`: the socket closed unexpectedly.
 */
export type CallPhase =
  | "idle"
  | "preparing"
  | "connecting"
  | "live"
  | "ending"
  | "ended"
  | "disconnected";

export interface CallLine {
  seq: number;
  speaker: Speaker;
  text: string;
}

export interface TimelineEntry {
  from: ConversationState;
  to: ConversationState;
  /** The receptionist turn this transition belongs to (the next `assistant.text`), when known. */
  turnSeq: number | null;
}

export interface LatencyRow {
  turnSeq: number;
  stt_ms: number | null;
  llm_ms: number | null;
  tts_first_byte_ms: number | null;
  total_ms: number | null;
}

export interface IntakeReport {
  turnSeq: number | null;
  missing: string[];
  rejected: Record<string, string>;
  corrected: string[];
}

export type ErrorSource = "server" | "api" | "socket" | "client";

export interface VoiceError {
  id: number;
  source: ErrorSource;
  code: string;
  message: string;
  provider: string | null;
  status: number | null;
  requestId: string | null;
}

export interface SocketClose {
  code: number;
  reason: string;
}

export interface VoiceCallState {
  phase: CallPhase;
  scenario: Scenario | null;
  conversation: Conversation | null;
  /** Reply audio format from `ready`. */
  audio: AudioFormat | null;
  /** The live conversation state, as last reported by the server. */
  state: ConversationState | null;
  lines: CallLine[];
  /** Provisional speech-to-text; display only, replaced by the committed utterance. */
  interim: string | null;
  /** The caller clip being spoken and transcribed right now. */
  clip: { clipId: string; durationMs: number } | null;
  /** The caller clip is audible right now (the `<audio>` element is playing it). */
  clipPlaying: boolean;
  /** A command sent and not yet answered (`assistant.text`, `error` or `closed`). */
  pending: ClientCommand["type"] | null;
  latestReceptionistTurn: number | null;
  /** The server is still streaming this turn's speech. */
  streamingTurn: number | null;
  /** Receptionist audio is audible right now (scheduled in the browser). */
  playing: boolean;
  cancelledTurns: number[];
  /** Receptionist turns the caller talked over. */
  bargeIns: number[];
  timeline: TimelineEntry[];
  latencies: LatencyRow[];
  intake: IntakeReport | null;
  /** Every intake report that rejected or corrected something, oldest first. */
  intakeHistory: IntakeReport[];
  errors: VoiceError[];
  closedState: ConversationState | null;
  lastClose: SocketClose | null;
  connections: number;
  ignoredMessageTypes: string[];
}

export const INITIAL_STATE: VoiceCallState = {
  phase: "idle",
  scenario: null,
  conversation: null,
  audio: null,
  state: null,
  lines: [],
  interim: null,
  clip: null,
  clipPlaying: false,
  pending: null,
  latestReceptionistTurn: null,
  streamingTurn: null,
  playing: false,
  cancelledTurns: [],
  bargeIns: [],
  timeline: [],
  latencies: [],
  intake: null,
  intakeHistory: [],
  errors: [],
  closedState: null,
  lastClose: null,
  connections: 0,
  ignoredMessageTypes: [],
};

export interface FailureInput {
  source: ErrorSource;
  code: string;
  message: string;
  provider?: string | null;
  status?: number | null;
  requestId?: string | null;
}

export type VoiceAction =
  | { type: "reset" }
  | { type: "prepare"; scenario: Scenario }
  | { type: "created"; conversation: Conversation }
  | { type: "connecting" }
  | { type: "socket_open" }
  | { type: "server"; message: ServerMessage }
  | { type: "unknown_message"; messageType: string }
  | { type: "command"; command: ClientCommand }
  | { type: "barge_in"; turnSeq: number | null }
  | { type: "playback"; playing: boolean }
  | { type: "clip_playback"; playing: boolean }
  | { type: "socket_closed"; code: number; reason: string }
  | { type: "failure"; error: FailureInput }
  | { type: "ended_by_api"; conversation: Conversation };

export function apiFailure(error: ApiError): FailureInput {
  return {
    source: "api",
    code: error.code,
    message: error.message,
    status: error.status > 0 ? error.status : null,
    requestId: error.requestId,
  };
}

function addError(state: VoiceCallState, input: FailureInput): VoiceError[] {
  const id = (state.errors.at(-1)?.id ?? 0) + 1;
  return [
    ...state.errors,
    {
      id,
      source: input.source,
      code: input.code,
      message: input.message,
      provider: input.provider ?? null,
      status: input.status ?? null,
      requestId: input.requestId ?? null,
    },
  ];
}

function upsertLatency(rows: LatencyRow[], row: LatencyRow): LatencyRow[] {
  const others = rows.filter((existing) => existing.turnSeq !== row.turnSeq);
  return [...others, row].sort((a, b) => a.turnSeq - b.turnSeq);
}

function transitions(message: Extract<ServerMessage, { type: "state" }>): TimelineEntry[] {
  const entries: TimelineEntry[] = [];
  let from = message.previous;
  for (const to of message.path) {
    entries.push({ from, to, turnSeq: null });
    from = to;
  }
  return entries;
}

function onServer(state: VoiceCallState, message: ServerMessage): VoiceCallState {
  switch (message.type) {
    case "ready": {
      const ended = TERMINAL_STATES.has(message.state);
      return {
        ...state,
        phase: ended ? "ended" : "live",
        audio: message.audio,
        state: message.state,
        closedState: ended ? message.state : state.closedState,
        pending: null,
      };
    }
    case "clip":
      return {
        ...state,
        clip: { clipId: message.clip_id, durationMs: message.duration_ms },
        interim: null,
      };
    case "transcript.interim":
      return { ...state, interim: message.text };
    case "utterance.final":
      return {
        ...state,
        interim: null,
        clip: null,
        lines: [...state.lines, { seq: message.turn_seq, speaker: "caller", text: message.text }],
      };
    case "state":
      return {
        ...state,
        state: message.state,
        timeline: [...state.timeline, ...transitions(message)],
      };
    case "assistant.text":
      return {
        ...state,
        pending: null,
        clip: null,
        interim: null,
        latestReceptionistTurn: message.turn_seq,
        streamingTurn: message.turn_seq,
        lines: [
          ...state.lines,
          { seq: message.turn_seq, speaker: "receptionist", text: message.text },
        ],
        timeline: state.timeline.map((entry) =>
          entry.turnSeq === null ? { ...entry, turnSeq: message.turn_seq } : entry,
        ),
      };
    case "assistant.audio_end":
      return {
        ...state,
        streamingTurn: state.streamingTurn === message.turn_seq ? null : state.streamingTurn,
      };
    case "assistant.audio_cancelled":
      return {
        ...state,
        streamingTurn: state.streamingTurn === message.turn_seq ? null : state.streamingTurn,
        cancelledTurns: state.cancelledTurns.includes(message.turn_seq)
          ? state.cancelledTurns
          : [...state.cancelledTurns, message.turn_seq],
      };
    case "intake": {
      const report: IntakeReport = {
        turnSeq: state.latestReceptionistTurn,
        missing: message.missing_fields,
        rejected: message.rejected_fields,
        corrected: message.corrected_fields,
      };
      const notable = Object.keys(report.rejected).length > 0 || report.corrected.length > 0;
      return {
        ...state,
        intake: report,
        intakeHistory: notable ? [...state.intakeHistory, report] : state.intakeHistory,
      };
    }
    case "latency":
      return {
        ...state,
        latencies: upsertLatency(state.latencies, {
          turnSeq: message.turn_seq,
          stt_ms: message.stt_ms,
          llm_ms: message.llm_ms,
          tts_first_byte_ms: message.tts_first_byte_ms,
          total_ms: message.total_ms,
        }),
      };
    case "closed":
      return {
        ...state,
        phase: "ended",
        state: message.state,
        closedState: message.state,
        pending: null,
        clip: null,
        interim: null,
      };
    case "error": {
      const errors = addError(state, {
        source: "server",
        code: message.code,
        message: message.message,
        provider: message.provider,
      });
      // BUSY refuses only the extra command; the earlier one is still being answered.
      const pending = message.code === "BUSY" ? state.pending : null;
      if (message.code === "CONVERSATION_CLOSED") {
        return { ...state, errors, pending, phase: "ended", clip: null, interim: null };
      }
      return { ...state, errors, pending, clip: pending === null ? null : state.clip };
    }
  }
}

export function voiceReducer(state: VoiceCallState, action: VoiceAction): VoiceCallState {
  switch (action.type) {
    case "reset":
      return INITIAL_STATE;
    case "prepare":
      return { ...INITIAL_STATE, phase: "preparing", scenario: action.scenario };
    case "created":
      return { ...state, conversation: action.conversation, state: action.conversation.state };
    case "connecting":
      return { ...state, phase: "connecting", lastClose: null };
    case "socket_open":
      return { ...state, connections: state.connections + 1 };
    case "server":
      return onServer(state, action.message);
    case "unknown_message":
      return state.ignoredMessageTypes.includes(action.messageType)
        ? state
        : { ...state, ignoredMessageTypes: [...state.ignoredMessageTypes, action.messageType] };
    case "command":
      if (action.command.type === "end") return { ...state, phase: "ending", pending: "end" };
      return { ...state, pending: action.command.type };
    case "barge_in":
      return action.turnSeq === null || state.bargeIns.includes(action.turnSeq)
        ? state
        : { ...state, bargeIns: [...state.bargeIns, action.turnSeq] };
    case "playback":
      return state.playing === action.playing ? state : { ...state, playing: action.playing };
    case "clip_playback":
      return state.clipPlaying === action.playing
        ? state
        : { ...state, clipPlaying: action.playing };
    case "socket_closed": {
      if (state.phase === "ended" || state.phase === "idle") return state;
      return {
        ...state,
        phase: "disconnected",
        lastClose: { code: action.code, reason: action.reason },
        pending: null,
        clip: null,
        interim: null,
        streamingTurn: null,
      };
    }
    case "failure": {
      const errors = addError(state, action.error);
      if (action.error.code === "CONVERSATION_CLOSED") {
        return { ...state, errors, phase: "ended", pending: null };
      }
      if (state.phase === "preparing") return { ...state, errors, phase: "idle" };
      if (state.phase === "connecting" || state.phase === "ending") {
        return { ...state, errors, phase: "disconnected", pending: null };
      }
      return { ...state, errors };
    }
    case "ended_by_api":
      return {
        ...state,
        phase: "ended",
        conversation: action.conversation,
        state: action.conversation.state,
        closedState: action.conversation.state,
        pending: null,
      };
  }
}

// --- selectors -----------------------------------------------------------------------------------

export function isTerminal(state: VoiceCallState): boolean {
  return state.state !== null && TERMINAL_STATES.has(state.state);
}

/** The receptionist is speaking: audio is playing here or still streaming from the server. */
export function receptionistSpeaking(state: VoiceCallState): boolean {
  return state.playing || state.streamingTurn !== null;
}

/** "Next caller line" is available: live, started, not finished, nothing waiting for an answer. */
export function canAdvance(state: VoiceCallState): boolean {
  return (
    state.phase === "live" &&
    state.pending === null &&
    state.state !== null &&
    state.state !== "CREATED" &&
    !isTerminal(state)
  );
}

export function canHangUp(state: VoiceCallState): boolean {
  return (
    state.conversation !== null &&
    (state.phase === "live" || state.phase === "connecting" || state.phase === "disconnected")
  );
}

export type Activity =
  | "connecting"
  | "greeting"
  | "caller_speaking"
  | "thinking"
  | "receptionist_speaking"
  | "your_turn"
  | "ended"
  | "disconnected"
  | "idle";

export function activity(state: VoiceCallState): Activity {
  if (state.phase === "ended") return "ended";
  if (state.phase === "disconnected") return "disconnected";
  if (state.phase === "preparing" || state.phase === "connecting") return "connecting";
  if (state.phase !== "live" && state.phase !== "ending") return "idle";
  if (state.pending === "start") return "greeting";
  if (state.clipPlaying) return "caller_speaking";
  if (state.pending === "next_clip") return "thinking";
  if (receptionistSpeaking(state)) return "receptionist_speaking";
  return "your_turn";
}
