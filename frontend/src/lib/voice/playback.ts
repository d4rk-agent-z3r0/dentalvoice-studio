// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
/**
 * Gapless playback of the receptionist's streamed speech with the Web Audio API.
 *
 * Each binary frame carries raw little-endian linear16 PCM for one receptionist turn. Frames are
 * converted to Float32 and scheduled back to back on one `AudioContext`: the first buffer of a run
 * starts slightly ahead of `currentTime`, every next one exactly where the previous ends, so there
 * are no gaps or overlaps between frames.
 *
 * Stale audio is dropped, never played:
 * - frames of a turn older than the latest `assistant.text` turn (the call has moved past it);
 * - frames of a turn that was cancelled (`assistant.audio_cancelled`, barge-in, hang-up).
 *
 * The context is injected (`PlaybackContext` is the subset of `AudioContext` used here), so tests
 * use a fake and nothing global is touched.
 */
import type { AudioFormat, AudioFrame } from "./protocol";

export interface PcmBuffer {
  readonly duration: number;
  getChannelData(channel: number): Float32Array;
}

export interface PcmSource {
  buffer: PcmBuffer | null;
  onended: ((event: Event) => void) | null;
  connect(destination: object): unknown;
  disconnect(): void;
  start(when?: number): void;
  stop(when?: number): void;
}

/** The part of `AudioContext` the player needs. A real `AudioContext` satisfies it. */
export interface PlaybackContext {
  readonly currentTime: number;
  readonly state: string;
  readonly destination: object;
  resume(): Promise<void>;
  close(): Promise<void>;
  createBuffer(channels: number, length: number, sampleRate: number): PcmBuffer;
  createBufferSource(): PcmSource;
}

export type FrameOutcome = "scheduled" | "stale" | "cancelled" | "empty";

/** How far ahead of `currentTime` a new run of audio starts, so the first buffer is not clipped. */
export const START_LEAD_SECONDS = 0.04;

/** Converts little-endian 16-bit PCM to Float32 samples in [-1, 1). */
export function int16ToFloat32(bytes: Uint8Array): Float32Array {
  const count = Math.floor(bytes.byteLength / 2);
  const view = new DataView(bytes.buffer, bytes.byteOffset, count * 2);
  const out = new Float32Array(count);
  for (let i = 0; i < count; i += 1) out[i] = view.getInt16(i * 2, true) / 32768;
  return out;
}

export interface PlayerStats {
  scheduledBuffers: number;
  scheduledSeconds: number;
  droppedFrames: number;
}

export class PcmPlayer {
  private readonly sources = new Map<PcmSource, number>();
  private readonly cancelled = new Set<number>();
  /** Every turn up to and including this one was interrupted (barge-in, hang-up). */
  private interruptedThrough = -1;
  private latestTurn = -1;
  private nextStart = 0;
  /** Bytes of an incomplete sample frame, carried to the next frame of the same turn. */
  private remainder: { turnSeq: number; bytes: Uint8Array } | null = null;
  private readonly counters: PlayerStats = { scheduledBuffers: 0, scheduledSeconds: 0, droppedFrames: 0 };

  constructor(
    private readonly context: PlaybackContext,
    private format: AudioFormat,
    private readonly onPlayingChange: (playing: boolean) => void = () => {},
  ) {}

  get playing(): boolean {
    return this.sources.size > 0;
  }

  get stats(): PlayerStats {
    return { ...this.counters };
  }

  /** The turn whose audio is currently scheduled, if any. */
  get playingTurn(): number | null {
    let turn: number | null = null;
    for (const value of this.sources.values()) turn = turn === null ? value : Math.max(turn, value);
    return turn;
  }

  setFormat(format: AudioFormat): void {
    this.format = format;
  }

  /** `assistant.text` arrived for `turnSeq`: older turns are now stale, and any of their audio stops. */
  beginTurn(turnSeq: number): void {
    if (turnSeq <= this.latestTurn) return;
    this.latestTurn = turnSeq;
    this.stopWhere((turn) => turn < turnSeq);
  }

  isStale(turnSeq: number): boolean {
    return turnSeq < this.latestTurn || this.isCancelled(turnSeq);
  }

  private isCancelled(turnSeq: number): boolean {
    return turnSeq <= this.interruptedThrough || this.cancelled.has(turnSeq);
  }

  push(frame: AudioFrame): FrameOutcome {
    if (this.isCancelled(frame.turnSeq)) {
      this.counters.droppedFrames += 1;
      return "cancelled";
    }
    if (frame.turnSeq < this.latestTurn) {
      this.counters.droppedFrames += 1;
      return "stale";
    }
    const { channels, sample_rate: sampleRate } = this.format;
    const bytes = this.withRemainder(frame);
    const frameBytes = 2 * channels;
    const usable = bytes.byteLength - (bytes.byteLength % frameBytes);
    this.remainder =
      usable < bytes.byteLength ? { turnSeq: frame.turnSeq, bytes: bytes.slice(usable) } : null;
    if (usable === 0) return "empty";

    const samples = int16ToFloat32(bytes.subarray(0, usable));
    const length = samples.length / channels;
    const buffer = this.context.createBuffer(channels, length, sampleRate);
    for (let channel = 0; channel < channels; channel += 1) {
      const data = buffer.getChannelData(channel);
      for (let i = 0; i < length; i += 1) data[i] = samples[i * channels + channel];
    }

    const source = this.context.createBufferSource();
    source.buffer = buffer;
    source.connect(this.context.destination);
    const startAt = Math.max(this.nextStart, this.context.currentTime + START_LEAD_SECONDS);
    const wasPlaying = this.playing;
    this.sources.set(source, frame.turnSeq);
    source.onended = () => {
      if (!this.sources.delete(source)) return;
      source.disconnect();
      if (!this.playing) this.onPlayingChange(false);
    };
    source.start(startAt);
    this.nextStart = startAt + buffer.duration;
    this.counters.scheduledBuffers += 1;
    this.counters.scheduledSeconds += buffer.duration;
    if (!wasPlaying) this.onPlayingChange(true);
    return "scheduled";
  }

  /** Stops one turn's audio and drops any of its frames still to come. */
  cancelTurn(turnSeq: number): void {
    this.cancelled.add(turnSeq);
    this.stopWhere((turn) => turn === turnSeq);
  }

  /**
   * Barge-in or hang-up: stops everything scheduled and drops every frame up to and including the
   * latest receptionist turn. A later turn (higher `turn_seq`) plays normally.
   */
  interrupt(): void {
    this.interruptedThrough = Math.max(
      this.interruptedThrough,
      this.latestTurn,
      this.playingTurn ?? -1,
    );
    this.stopWhere(() => true);
  }

  async close(): Promise<void> {
    this.interrupt();
    if (this.context.state !== "closed") await this.context.close();
  }

  private withRemainder(frame: AudioFrame): Uint8Array {
    const carried = this.remainder;
    if (carried === null || carried.turnSeq !== frame.turnSeq) return frame.pcm;
    const joined = new Uint8Array(carried.bytes.byteLength + frame.pcm.byteLength);
    joined.set(carried.bytes, 0);
    joined.set(frame.pcm, carried.bytes.byteLength);
    return joined;
  }

  private stopWhere(match: (turn: number) => boolean): void {
    const wasPlaying = this.playing;
    for (const [source, turn] of [...this.sources]) {
      if (!match(turn)) continue;
      this.sources.delete(source);
      source.onended = null;
      try {
        source.stop();
      } catch {
        // Already stopped: nothing left to silence.
      }
      source.disconnect();
    }
    if (this.remainder !== null && match(this.remainder.turnSeq)) this.remainder = null;
    if (!this.playing) {
      this.nextStart = 0;
      if (wasPlaying) this.onPlayingChange(false);
    }
  }
}
