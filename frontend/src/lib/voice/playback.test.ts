// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import { describe, expect, it } from "vitest";

import { FakeAudioContext, FakeBuffer } from "@/test/voice-fakes";

import { PcmPlayer, START_LEAD_SECONDS, int16ToFloat32 } from "./playback";
import type { AudioFormat } from "./protocol";

const MONO_8K: AudioFormat = { sample_rate: 8000, encoding: "linear16", channels: 1 };

function pcm(samples: number[]): Uint8Array {
  const bytes = new Uint8Array(samples.length * 2);
  const view = new DataView(bytes.buffer);
  samples.forEach((sample, index) => view.setInt16(index * 2, sample, true));
  return bytes;
}

function setup(format: AudioFormat = MONO_8K) {
  const context = new FakeAudioContext();
  const changes: boolean[] = [];
  const player = new PcmPlayer(context, format, (playing) => changes.push(playing));
  return { context, player, changes };
}

describe("int16ToFloat32", () => {
  it("scales little-endian int16 to [-1, 1)", () => {
    expect(Array.from(int16ToFloat32(pcm([0, 16384, -32768, 32767])))).toEqual([
      0,
      0.5,
      -1,
      32767 / 32768,
    ]);
  });

  it("reads from a byte offset inside a larger buffer", () => {
    const frame = new Uint8Array([9, 9, 9, 9, ...pcm([-16384])]);
    expect(Array.from(int16ToFloat32(frame.subarray(4)))).toEqual([-0.5]);
  });
});

describe("PcmPlayer", () => {
  it("schedules frames back to back without gaps", () => {
    const { context, player, changes } = setup();
    context.currentTime = 1;
    player.beginTurn(1);
    expect(player.push({ turnSeq: 1, pcm: pcm(new Array(800).fill(100)) })).toBe("scheduled");
    expect(player.push({ turnSeq: 1, pcm: pcm(new Array(400).fill(100)) })).toBe("scheduled");
    context.currentTime = 1.05;
    expect(player.push({ turnSeq: 1, pcm: pcm(new Array(1600).fill(100)) })).toBe("scheduled");

    const starts = context.sources.map((source) => source.startedAt);
    expect(starts[0]).toBeCloseTo(1 + START_LEAD_SECONDS);
    expect(starts[1]).toBeCloseTo(1 + START_LEAD_SECONDS + 0.1); // 800 samples at 8 kHz
    expect(starts[2]).toBeCloseTo(1 + START_LEAD_SECONDS + 0.15);
    expect(context.sources.every((source) => source.connected)).toBe(true);
    expect(player.stats).toMatchObject({ scheduledBuffers: 3, droppedFrames: 0 });
    expect(player.stats.scheduledSeconds).toBeCloseTo(0.35);
    expect(changes).toEqual([true]);

    context.sources.forEach((source) => source.finish());
    expect(player.playing).toBe(false);
    expect(changes).toEqual([true, false]);
  });

  it("starts a new run slightly ahead of now after an underrun", () => {
    const { context, player } = setup();
    player.beginTurn(1);
    player.push({ turnSeq: 1, pcm: pcm([1, 2]) });
    context.sources[0].finish();
    context.currentTime = 5;
    player.push({ turnSeq: 1, pcm: pcm([1, 2]) });
    expect(context.sources[1].startedAt).toBeCloseTo(5 + START_LEAD_SECONDS);
  });

  it("writes Float32 samples into the buffer and de-interleaves stereo", () => {
    const { context, player } = setup({ sample_rate: 8000, encoding: "linear16", channels: 2 });
    player.beginTurn(1);
    player.push({ turnSeq: 1, pcm: pcm([16384, -16384, 0, 32767]) });
    const buffer = context.sources[0].buffer as FakeBuffer;
    expect(buffer.length).toBe(2);
    expect(Array.from(buffer.channels[0])).toEqual([0.5, 0]);
    expect(Array.from(buffer.channels[1])).toEqual([-0.5, 32767 / 32768]);
  });

  it("carries an odd trailing byte into the next frame of the same turn", () => {
    const { context, player } = setup();
    player.beginTurn(1);
    const bytes = pcm([16384, -16384]);
    expect(player.push({ turnSeq: 1, pcm: bytes.subarray(0, 3) })).toBe("scheduled");
    expect(player.push({ turnSeq: 1, pcm: bytes.subarray(3) })).toBe("scheduled");
    const buffers = context.sources.map((source) => Array.from((source.buffer as FakeBuffer).channels[0]));
    expect(buffers).toEqual([[0.5], [-0.5]]);
  });

  it("drops frames of a turn older than the latest assistant.text turn", () => {
    const { context, player } = setup();
    player.beginTurn(3);
    player.push({ turnSeq: 3, pcm: pcm([1, 1]) });
    player.beginTurn(5);
    // The older turn's audio stops as soon as a newer turn begins.
    expect(context.sources[0].stopped).toBe(true);
    expect(player.push({ turnSeq: 3, pcm: pcm([1, 1]) })).toBe("stale");
    expect(player.push({ turnSeq: 5, pcm: pcm([1, 1]) })).toBe("scheduled");
    expect(player.isStale(3)).toBe(true);
    expect(player.isStale(5)).toBe(false);
    expect(player.stats.droppedFrames).toBe(1);
    expect(context.sources).toHaveLength(2);
  });

  it("ignores a beginTurn for an older turn", () => {
    const { player } = setup();
    player.beginTurn(5);
    player.beginTurn(3);
    expect(player.push({ turnSeq: 3, pcm: pcm([1]) })).toBe("stale");
  });

  it("stops a cancelled turn and drops the rest of its frames", () => {
    const { context, player, changes } = setup();
    player.beginTurn(3);
    player.push({ turnSeq: 3, pcm: pcm([1, 1]) });
    player.push({ turnSeq: 3, pcm: pcm([1, 1]) });
    player.cancelTurn(3);
    expect(context.sources.every((source) => source.stopped && !source.connected)).toBe(true);
    expect(player.playing).toBe(false);
    expect(changes).toEqual([true, false]);
    expect(player.push({ turnSeq: 3, pcm: pcm([1, 1]) })).toBe("cancelled");
    expect(context.sources).toHaveLength(2);
  });

  it("interrupt (barge-in) silences everything and drops late frames, but a newer turn plays", () => {
    const { context, player } = setup();
    player.beginTurn(3);
    player.push({ turnSeq: 3, pcm: pcm([1, 1]) });
    player.interrupt();
    expect(context.active).toHaveLength(0);
    expect(player.push({ turnSeq: 3, pcm: pcm([1, 1]) })).toBe("cancelled");
    expect(player.push({ turnSeq: 2, pcm: pcm([1, 1]) })).toBe("cancelled");
    player.beginTurn(5);
    expect(player.push({ turnSeq: 5, pcm: pcm([1, 1]) })).toBe("scheduled");
  });

  it("a stopped source's late onended does not flip the playing state", () => {
    const { context, player, changes } = setup();
    player.beginTurn(1);
    player.push({ turnSeq: 1, pcm: pcm([1]) });
    const source = context.sources[0];
    player.interrupt();
    source.finish(); // onended was detached; nothing happens
    expect(changes).toEqual([true, false]);
  });

  it("close() interrupts and closes the context", async () => {
    const { context, player } = setup();
    player.beginTurn(1);
    player.push({ turnSeq: 1, pcm: pcm([1]) });
    await player.close();
    expect(context.state).toBe("closed");
    expect(context.active).toHaveLength(0);
  });
});
