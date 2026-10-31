// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
/**
 * The conversation WebSocket protocol (`docs/api-reference.md`, "Voice — shipped in M5"), parsed
 * strictly. Framework-free so it can be unit tested without a browser.
 *
 * Every server text frame becomes one of three outcomes:
 * - a typed `ServerMessage`;
 * - `unknown` for a well-formed message of a type this client does not know (a newer server);
 * - `invalid` for anything malformed. Malformed messages are reported, never guessed at.
 */
import { isConversationState, type ConversationState } from "@/lib/api/types";

export interface AudioFormat {
  sample_rate: number;
  encoding: "linear16";
  channels: number;
}

export type ServerMessage =
  | { type: "ready"; state: ConversationState; audio: AudioFormat }
  | { type: "clip"; clip_id: string; url: string; duration_ms: number }
  | { type: "transcript.interim"; text: string }
  | { type: "utterance.final"; turn_seq: number; text: string }
  | { type: "state"; state: ConversationState; previous: ConversationState; path: ConversationState[] }
  | { type: "assistant.text"; turn_seq: number; text: string }
  | { type: "assistant.audio_end"; turn_seq: number }
  | { type: "assistant.audio_cancelled"; turn_seq: number }
  | {
      type: "intake";
      missing_fields: string[];
      rejected_fields: Record<string, string>;
      corrected_fields: string[];
    }
  | {
      type: "latency";
      turn_seq: number;
      stt_ms: number | null;
      llm_ms: number | null;
      tts_first_byte_ms: number | null;
      total_ms: number | null;
    }
  | { type: "closed"; state: ConversationState }
  | { type: "error"; code: string; message: string; provider: string | null };

export type ServerMessageType = ServerMessage["type"];

export type ParsedMessage =
  | { kind: "message"; message: ServerMessage }
  | { kind: "unknown"; type: string }
  | { kind: "invalid"; reason: string };

export type ClientCommand = { type: "start" } | { type: "next_clip" } | { type: "end" };

export function encodeCommand(command: ClientCommand): string {
  return JSON.stringify(command);
}

// --- field readers -------------------------------------------------------------------------------

class Invalid extends Error {}

type Json = Record<string, unknown>;

function isRecord(value: unknown): value is Json {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function str(body: Json, key: string): string {
  const value = body[key];
  if (typeof value !== "string") throw new Invalid(`"${key}" must be a string`);
  return value;
}

function seq(body: Json, key: string): number {
  const value = body[key];
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    throw new Invalid(`"${key}" must be a non-negative integer`);
  }
  return value;
}

/** A measured duration: a non-negative number, or `null` when the stage did not happen. */
function ms(body: Json, key: string): number | null {
  const value = body[key];
  if (value === null) return null;
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
    throw new Invalid(`"${key}" must be a non-negative number or null`);
  }
  return value;
}

function state(body: Json, key: string): ConversationState {
  const value = str(body, key);
  if (!isConversationState(value)) throw new Invalid(`"${key}" is not a conversation state`);
  return value;
}

function states(body: Json, key: string): ConversationState[] {
  const value = body[key];
  if (!Array.isArray(value)) throw new Invalid(`"${key}" must be a list`);
  return value.map((item) => {
    if (typeof item !== "string" || !isConversationState(item)) {
      throw new Invalid(`"${key}" holds an unknown state`);
    }
    return item;
  });
}

function strings(body: Json, key: string): string[] {
  const value = body[key];
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
    throw new Invalid(`"${key}" must be a list of strings`);
  }
  return value as string[];
}

function reasons(body: Json, key: string): Record<string, string> {
  const value = body[key];
  if (!isRecord(value) || Object.values(value).some((item) => typeof item !== "string")) {
    throw new Invalid(`"${key}" must map fields to reasons`);
  }
  return { ...(value as Record<string, string>) };
}

function audioFormat(body: Json): AudioFormat {
  const audio = body.audio;
  if (!isRecord(audio)) throw new Invalid(`"audio" must be an object`);
  if (audio.encoding !== "linear16") throw new Invalid(`only linear16 audio is supported`);
  const sampleRate = audio.sample_rate;
  const channels = audio.channels;
  if (typeof sampleRate !== "number" || !Number.isInteger(sampleRate) || sampleRate < 3000) {
    throw new Invalid(`"audio.sample_rate" must be an integer of at least 3000`);
  }
  if (typeof channels !== "number" || !Number.isInteger(channels) || channels < 1 || channels > 8) {
    throw new Invalid(`"audio.channels" must be an integer from 1 to 8`);
  }
  return { sample_rate: sampleRate, encoding: "linear16", channels };
}

const READERS: { [K in ServerMessageType]: (body: Json) => Extract<ServerMessage, { type: K }> } = {
  ready: (b) => ({ type: "ready", state: state(b, "state"), audio: audioFormat(b) }),
  clip: (b) => ({
    type: "clip",
    clip_id: str(b, "clip_id"),
    url: str(b, "url"),
    duration_ms: seq(b, "duration_ms"),
  }),
  "transcript.interim": (b) => ({ type: "transcript.interim", text: str(b, "text") }),
  "utterance.final": (b) => ({
    type: "utterance.final",
    turn_seq: seq(b, "turn_seq"),
    text: str(b, "text"),
  }),
  state: (b) => ({
    type: "state",
    state: state(b, "state"),
    previous: state(b, "previous"),
    path: states(b, "path"),
  }),
  "assistant.text": (b) => ({
    type: "assistant.text",
    turn_seq: seq(b, "turn_seq"),
    text: str(b, "text"),
  }),
  "assistant.audio_end": (b) => ({ type: "assistant.audio_end", turn_seq: seq(b, "turn_seq") }),
  "assistant.audio_cancelled": (b) => ({
    type: "assistant.audio_cancelled",
    turn_seq: seq(b, "turn_seq"),
  }),
  intake: (b) => ({
    type: "intake",
    missing_fields: strings(b, "missing_fields"),
    rejected_fields: reasons(b, "rejected_fields"),
    corrected_fields: strings(b, "corrected_fields"),
  }),
  latency: (b) => ({
    type: "latency",
    turn_seq: seq(b, "turn_seq"),
    stt_ms: ms(b, "stt_ms"),
    llm_ms: ms(b, "llm_ms"),
    tts_first_byte_ms: ms(b, "tts_first_byte_ms"),
    total_ms: ms(b, "total_ms"),
  }),
  closed: (b) => ({ type: "closed", state: state(b, "state") }),
  error: (b) => {
    const provider = b.provider;
    if (provider !== undefined && provider !== null && typeof provider !== "string") {
      throw new Invalid(`"provider" must be a string`);
    }
    return {
      type: "error",
      code: str(b, "code"),
      message: str(b, "message"),
      provider: provider ?? null,
    };
  },
};

function isKnownType(type: string): type is ServerMessageType {
  return Object.hasOwn(READERS, type);
}

function read<K extends ServerMessageType>(type: K, body: Json): ServerMessage {
  return READERS[type](body);
}

/** Parses one server text frame. Never throws. */
export function parseServerMessage(text: string): ParsedMessage {
  let body: unknown;
  try {
    body = JSON.parse(text);
  } catch {
    return { kind: "invalid", reason: "not JSON" };
  }
  if (!isRecord(body) || typeof body.type !== "string") {
    return { kind: "invalid", reason: "not an object with a string type" };
  }
  const type = body.type;
  if (!isKnownType(type)) return { kind: "unknown", type };
  try {
    return { kind: "message", message: read(type, body) };
  } catch (error) {
    if (error instanceof Invalid) return { kind: "invalid", reason: `${type}: ${error.message}` };
    throw error;
  }
}

// --- binary frames -------------------------------------------------------------------------------

export interface AudioFrame {
  turnSeq: number;
  /** Raw linear16 PCM bytes, little-endian, in the `ready` format. */
  pcm: Uint8Array;
}

export const FRAME_HEADER_BYTES = 4;

/** A binary frame is a 4-byte big-endian `turn_seq` followed by PCM; shorter frames are invalid. */
export function parseAudioFrame(data: ArrayBuffer): AudioFrame | null {
  if (data.byteLength < FRAME_HEADER_BYTES) return null;
  const turnSeq = new DataView(data).getUint32(0, false);
  return { turnSeq, pcm: new Uint8Array(data, FRAME_HEADER_BYTES) };
}

// --- admission -----------------------------------------------------------------------------------

/**
 * The socket URL for a conversation, derived from the API base URL (`http` → `ws`, `https` →
 * `wss`). Only the single-use ticket goes in the query string; the access token never does
 * (ADR-0006).
 */
export function conversationSocketUrl(apiBaseUrl: string, conversationId: string, ticket: string) {
  const url = new URL(apiBaseUrl);
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error(`Unsupported API base URL protocol: ${url.protocol}`);
  }
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  const base = url.pathname.replace(/\/+$/, "");
  url.pathname = `${base}/api/v1/ws/conversations/${encodeURIComponent(conversationId)}`;
  url.search = new URLSearchParams({ ticket }).toString();
  url.hash = "";
  return url.toString();
}
