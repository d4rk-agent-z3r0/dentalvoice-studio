// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import { describe, expect, it } from "vitest";

import { audioFrame } from "@/test/voice-fakes";

import {
  conversationSocketUrl,
  encodeCommand,
  parseAudioFrame,
  parseServerMessage,
} from "./protocol";

const parse = (body: unknown) => parseServerMessage(JSON.stringify(body));

describe("parseServerMessage", () => {
  it("reads every message type of the M5 protocol", () => {
    const messages = [
      { type: "ready", state: "CREATED", audio: { sample_rate: 24000, encoding: "linear16", channels: 1 } },
      { type: "clip", clip_id: "a-01", url: "/api/v1/audio/clips/a-01", duration_ms: 3120 },
      { type: "transcript.interim", text: "Hi! I'd like" },
      { type: "utterance.final", turn_seq: 2, text: "Hi! I'd like to book a teeth cleaning." },
      { type: "state", state: "IDENTITY_COLLECTION", previous: "GREETING", path: ["INTRODUCTION", "IDENTITY_COLLECTION"] },
      { type: "assistant.text", turn_seq: 3, text: "Could I have your name?" },
      { type: "assistant.audio_end", turn_seq: 3 },
      { type: "assistant.audio_cancelled", turn_seq: 3 },
      {
        type: "intake",
        missing_fields: ["first_name"],
        rejected_fields: { email: "Only reserved example domains are allowed." },
        corrected_fields: ["phone"],
      },
      { type: "latency", turn_seq: 3, stt_ms: 41, llm_ms: 3, tts_first_byte_ms: 0, total_ms: 46 },
      { type: "closed", state: "COMPLETED" },
      { type: "error", code: "PROVIDER_ERROR", message: "A speech or language provider failed.", provider: "deepgram" },
    ];
    for (const body of messages) {
      const parsed = parse(body);
      expect(parsed.kind, body.type).toBe("message");
      if (parsed.kind === "message") expect(parsed.message).toEqual(body);
    }
  });

  it("keeps null latencies as null (never 0)", () => {
    const parsed = parse({ type: "latency", turn_seq: 1, stt_ms: null, llm_ms: null, tts_first_byte_ms: 2, total_ms: null });
    expect(parsed).toEqual({
      kind: "message",
      message: { type: "latency", turn_seq: 1, stt_ms: null, llm_ms: null, tts_first_byte_ms: 2, total_ms: null },
    });
  });

  it("reads an error without a provider as provider null", () => {
    expect(parse({ type: "error", code: "NO_MORE_CLIPS", message: "No more clips." })).toEqual({
      kind: "message",
      message: { type: "error", code: "NO_MORE_CLIPS", message: "No more clips.", provider: null },
    });
  });

  it("reports unknown message types instead of guessing", () => {
    expect(parse({ type: "assistant.mood", value: "cheerful" })).toEqual({
      kind: "unknown",
      type: "assistant.mood",
    });
    // Not a prototype key either.
    expect(parse({ type: "toString" })).toEqual({ kind: "unknown", type: "toString" });
  });

  it.each([
    ["not JSON", "{oops"],
    ["no type", JSON.stringify({ text: "hi" })],
    ["an array", JSON.stringify([1, 2])],
    ["a latency of zero replaced by a string", JSON.stringify({ type: "latency", turn_seq: 1, stt_ms: "0", llm_ms: null, tts_first_byte_ms: null, total_ms: null })],
    ["a missing latency field", JSON.stringify({ type: "latency", turn_seq: 1, stt_ms: null })],
    ["an unknown state", JSON.stringify({ type: "closed", state: "FINISHED" })],
    ["a negative turn", JSON.stringify({ type: "assistant.text", turn_seq: -1, text: "x" })],
    ["a fractional turn", JSON.stringify({ type: "utterance.final", turn_seq: 1.5, text: "x" })],
    ["non-string reasons", JSON.stringify({ type: "intake", missing_fields: [], rejected_fields: { email: 1 }, corrected_fields: [] })],
    ["a non-linear16 format", JSON.stringify({ type: "ready", state: "CREATED", audio: { sample_rate: 24000, encoding: "mulaw", channels: 1 } })],
  ])("marks %s as invalid", (_, raw) => {
    expect(parseServerMessage(raw).kind).toBe("invalid");
  });
});

describe("parseAudioFrame", () => {
  it("reads the 4-byte big-endian turn number and keeps the PCM bytes", () => {
    const frame = parseAudioFrame(audioFrame(258, [1, -2, 32767]));
    expect(frame?.turnSeq).toBe(258);
    expect(frame?.pcm.byteLength).toBe(6);
    expect(Array.from(frame!.pcm)).toEqual([1, 0, 0xfe, 0xff, 0xff, 0x7f]);
  });

  it("reads large turn numbers as unsigned", () => {
    const buffer = new ArrayBuffer(6);
    new DataView(buffer).setUint32(0, 0x80000001, false);
    expect(parseAudioFrame(buffer)?.turnSeq).toBe(0x80000001);
  });

  it("accepts a header-only frame and rejects anything shorter", () => {
    expect(parseAudioFrame(new ArrayBuffer(4))?.pcm.byteLength).toBe(0);
    expect(parseAudioFrame(new ArrayBuffer(3))).toBeNull();
  });
});

describe("conversationSocketUrl", () => {
  it("derives ws:// from http:// and puts only the ticket in the query", () => {
    expect(conversationSocketUrl("http://localhost:8012", "c-1", "t/k+n=")).toBe(
      "ws://localhost:8012/api/v1/ws/conversations/c-1?ticket=t%2Fk%2Bn%3D",
    );
  });

  it("derives wss:// from https:// and keeps a path prefix", () => {
    expect(conversationSocketUrl("https://demo.example.com/backend/", "c-2", "abc")).toBe(
      "wss://demo.example.com/backend/api/v1/ws/conversations/c-2?ticket=abc",
    );
  });

  it("refuses other protocols", () => {
    expect(() => conversationSocketUrl("ftp://example.com", "c", "t")).toThrow();
  });
});

describe("encodeCommand", () => {
  it("encodes the three client commands as small JSON text frames", () => {
    expect(encodeCommand({ type: "start" })).toBe('{"type":"start"}');
    expect(encodeCommand({ type: "next_clip" })).toBe('{"type":"next_clip"}');
    expect(encodeCommand({ type: "end" })).toBe('{"type":"end"}');
  });
});
