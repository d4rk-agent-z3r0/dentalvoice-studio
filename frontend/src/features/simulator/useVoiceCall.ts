// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
"use client";

import { useEffect, useState, useSyncExternalStore } from "react";

import { API_BASE_URL, useApiClient } from "@/lib/api/ApiProvider";
import { VoiceCall, type ClipOutput, type VoiceEnvironment } from "@/lib/voice/call";
import type { VoiceCallState } from "@/lib/voice/session";

/**
 * Binds one `VoiceCall` to the component's lifetime. The call object outlives re-renders; the
 * socket, audio context and caller clip are released on unmount.
 */
export function useVoiceCall(
  environment: VoiceEnvironment,
  clipOutput: ClipOutput,
): { call: VoiceCall; state: VoiceCallState } {
  const api = useApiClient();
  const [call] = useState(
    () => new VoiceCall({ ...environment, api, apiBaseUrl: API_BASE_URL, clipOutput }),
  );
  useEffect(() => call.setApi(api), [call, api]);
  useEffect(() => () => call.dispose(), [call]);
  const state = useSyncExternalStore(call.subscribe, call.getSnapshot, call.getSnapshot);
  return { call, state };
}

export type AudioElementOutput = ClipOutput & { attach(element: HTMLAudioElement | null): void };

/**
 * Plays caller clips through an `<audio>` element. `attach` is the element's callback ref, so the
 * output always uses the mounted element.
 */
export function audioElementOutput(): AudioElementOutput {
  let audio: HTMLAudioElement | null = null;
  return {
    attach(element) {
      audio = element;
    },
    async play(src, onEnded) {
      const element = audio;
      if (element === null) throw new Error("The audio element is not mounted.");
      element.onended = () => {
        element.onended = null;
        onEnded();
      };
      element.src = src;
      await element.play();
    },
    stop() {
      const element = audio;
      if (element === null) return;
      element.onended = null;
      element.pause();
      element.removeAttribute("src");
      element.load();
    },
  };
}
