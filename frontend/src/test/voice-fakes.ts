// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
/**
 * Injected fakes for the voice call: a socket, an `AudioContext`, a clip output and object URLs.
 * Nothing global is patched, so tests cannot leak into each other.
 */
import type { ClipOutput, VoiceEnvironment, VoiceSocketHandlers } from "@/lib/voice/call";
import type { PcmBuffer, PcmSource, PlaybackContext } from "@/lib/voice/playback";

// --- socket --------------------------------------------------------------------------------------

export class FakeSocket {
  readonly sent: string[] = [];
  closedByClient: { code?: number; reason?: string } | null = null;

  constructor(
    readonly url: string,
    private readonly handlers: VoiceSocketHandlers,
  ) {}

  /** Commands the page sent, decoded. */
  get commands(): string[] {
    return this.sent.map((text) => (JSON.parse(text) as { type: string }).type);
  }

  open(): void {
    this.handlers.onOpen();
  }

  /** A server JSON message (`{type, ...payload}`). */
  message(body: Record<string, unknown>): void {
    this.handlers.onText(JSON.stringify(body));
  }

  text(raw: string): void {
    this.handlers.onText(raw);
  }

  /** A binary audio frame: 4-byte big-endian turn_seq + little-endian int16 samples. */
  audio(turnSeq: number, samples: number[] | Int16Array): void {
    this.handlers.onBinary(audioFrame(turnSeq, samples));
  }

  serverClose(code: number, reason = ""): void {
    this.handlers.onClose(code, reason);
  }
}

export function audioFrame(turnSeq: number, samples: number[] | Int16Array): ArrayBuffer {
  const buffer = new ArrayBuffer(4 + samples.length * 2);
  const view = new DataView(buffer);
  view.setUint32(0, turnSeq, false);
  Array.from(samples).forEach((sample, index) => view.setInt16(4 + index * 2, sample, true));
  return buffer;
}

// --- audio ---------------------------------------------------------------------------------------

export class FakeBuffer implements PcmBuffer {
  readonly channels: Float32Array[];

  constructor(
    channelCount: number,
    readonly length: number,
    readonly sampleRate: number,
  ) {
    this.channels = Array.from({ length: channelCount }, () => new Float32Array(length));
  }

  get duration(): number {
    return this.length / this.sampleRate;
  }

  getChannelData(channel: number): Float32Array {
    return this.channels[channel];
  }
}

export class FakeSource implements PcmSource {
  buffer: PcmBuffer | null = null;
  onended: ((event: Event) => void) | null = null;
  startedAt: number | null = null;
  stopped = false;
  connected = false;

  connect(): unknown {
    this.connected = true;
    return undefined;
  }

  disconnect(): void {
    this.connected = false;
  }

  start(when = 0): void {
    this.startedAt = when;
  }

  stop(): void {
    this.stopped = true;
  }

  /** Simulates the buffer playing to its end. */
  finish(): void {
    this.ended = true;
    this.onended?.(new Event("ended"));
  }

  ended = false;
}

export class FakeAudioContext implements PlaybackContext {
  currentTime = 0;
  state: "suspended" | "running" | "closed" = "suspended";
  readonly destination = {};
  readonly sources: FakeSource[] = [];
  resumeCalls = 0;

  async resume(): Promise<void> {
    this.resumeCalls += 1;
    this.state = "running";
  }

  async close(): Promise<void> {
    this.state = "closed";
  }

  createBuffer(channels: number, length: number, sampleRate: number): FakeBuffer {
    return new FakeBuffer(channels, length, sampleRate);
  }

  createBufferSource(): FakeSource {
    const source = new FakeSource();
    this.sources.push(source);
    return source;
  }

  /** Sources that were started and neither stopped nor finished. */
  get active(): FakeSource[] {
    return this.sources.filter(
      (source) => source.startedAt !== null && !source.stopped && !source.ended,
    );
  }
}

// --- clip output ---------------------------------------------------------------------------------

export class FakeClipOutput implements ClipOutput {
  readonly played: string[] = [];
  stops = 0;
  private ended: (() => void) | null = null;
  failWith: Error | null = null;

  async play(src: string, onEnded: () => void): Promise<void> {
    if (this.failWith) throw this.failWith;
    this.played.push(src);
    this.ended = onEnded;
  }

  stop(): void {
    this.stops += 1;
    this.ended = null;
  }

  /** The clip played to its end. */
  finish(): void {
    const ended = this.ended;
    this.ended = null;
    ended?.();
  }
}

// --- environment ---------------------------------------------------------------------------------

export interface FakeVoiceEnvironment extends VoiceEnvironment {
  sockets: FakeSocket[];
  contexts: FakeAudioContext[];
  /** The latest socket (fails the test when none was opened). */
  socket(): FakeSocket;
  context(): FakeAudioContext;
  createdUrls: string[];
  revokedUrls: string[];
}

export function fakeVoiceEnvironment(): FakeVoiceEnvironment {
  const sockets: FakeSocket[] = [];
  const contexts: FakeAudioContext[] = [];
  const createdUrls: string[] = [];
  const revokedUrls: string[] = [];
  return {
    sockets,
    contexts,
    createdUrls,
    revokedUrls,
    socket() {
      const latest = sockets.at(-1);
      if (!latest) throw new Error("No socket was opened.");
      return latest;
    },
    context() {
      const latest = contexts.at(-1);
      if (!latest) throw new Error("No AudioContext was created.");
      return latest;
    },
    createSocket(url, handlers) {
      const socket = new FakeSocket(url, handlers);
      sockets.push(socket);
      return {
        send: (text) => socket.sent.push(text),
        close: (code, reason) => {
          socket.closedByClient = { code, reason };
        },
      };
    },
    createAudioContext() {
      const context = new FakeAudioContext();
      contexts.push(context);
      return context;
    },
    createObjectUrl() {
      const url = `blob:fake/${createdUrls.length + 1}`;
      createdUrls.push(url);
      return url;
    },
    revokeObjectUrl(url) {
      revokedUrls.push(url);
    },
  };
}

// --- scripted server messages ---------------------------------------------------------------------

export const READY_CREATED = {
  type: "ready",
  state: "CREATED",
  audio: { sample_rate: 24000, encoding: "linear16", channels: 1 },
};

export function latency(
  turnSeq: number,
  values: Partial<Record<"stt_ms" | "llm_ms" | "tts_first_byte_ms" | "total_ms", number | null>> = {},
) {
  return {
    type: "latency",
    turn_seq: turnSeq,
    stt_ms: null,
    llm_ms: null,
    tts_first_byte_ms: null,
    total_ms: null,
    ...values,
  };
}
