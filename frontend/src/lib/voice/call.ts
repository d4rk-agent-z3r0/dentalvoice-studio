// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
/**
 * One voice call, framework-free: REST admission, the socket, caller clip playback and receptionist
 * audio, feeding `voiceReducer`. React subscribes through `subscribe`/`getSnapshot`
 * (`useSyncExternalStore`); everything with a side effect is injected so tests can drive a whole
 * call with a fake socket and a fake `AudioContext`.
 *
 * Admission (ADR-0006): `POST /conversations` → `POST /conversations/{id}/ws-ticket` → socket
 * `?ticket=…`. The access token is only ever sent as a bearer header over REST, never in the
 * socket URL. No microphone is used: caller audio is the scenario's synthetic clips (ADR-0002).
 */
import type { ApiClient } from "@/lib/api/client";
import { toApiError } from "@/lib/api/errors";
import type { Scenario } from "@/lib/api/types";

import { PcmPlayer, type PlaybackContext } from "./playback";
import {
  conversationSocketUrl,
  encodeCommand,
  parseAudioFrame,
  parseServerMessage,
  type ClientCommand,
  type ServerMessage,
} from "./protocol";
import {
  INITIAL_STATE,
  apiFailure,
  canAdvance,
  canHangUp,
  receptionistSpeaking,
  voiceReducer,
  type VoiceAction,
  type VoiceCallState,
} from "./session";

export interface VoiceSocketHandlers {
  onOpen(): void;
  onText(text: string): void;
  onBinary(data: ArrayBuffer): void;
  onClose(code: number, reason: string): void;
}

/** The socket as the call uses it. `browserSocket` adapts a real `WebSocket`. */
export interface VoiceSocket {
  send(text: string): void;
  close(code?: number, reason?: string): void;
}

export type SocketFactory = (url: string, handlers: VoiceSocketHandlers) => VoiceSocket;

/** Plays a caller clip from a (blob) URL; `onEnded` fires once when it finishes on its own. */
export interface ClipOutput {
  play(src: string, onEnded: () => void): Promise<void>;
  stop(): void;
}

export type VoiceApi = Pick<
  ApiClient,
  "createConversation" | "issueWsTicket" | "getClipAudio" | "endConversation"
>;

export interface VoiceEnvironment {
  createSocket: SocketFactory;
  createAudioContext: () => PlaybackContext;
  createObjectUrl: (blob: Blob) => string;
  revokeObjectUrl: (url: string) => void;
}

export interface VoiceCallOptions extends VoiceEnvironment {
  api: VoiceApi;
  apiBaseUrl: string;
  clipOutput: ClipOutput;
}

/** Normal closure, sent when the page closes the socket itself (hang-up handled, reset, unmount). */
const CLOSE_NORMAL = 1000;

export class VoiceCall {
  private state: VoiceCallState = INITIAL_STATE;
  private readonly listeners = new Set<() => void>();
  private api: VoiceApi;
  private socket: VoiceSocket | null = null;
  private socketOpen = false;
  /** Incremented per connection, so events of a replaced socket are ignored. */
  private generation = 0;
  private context: PlaybackContext | null = null;
  private player: PcmPlayer | null = null;
  private clipToken = 0;
  private clipUrl: string | null = null;
  private audioUnavailableReported = false;

  constructor(private readonly options: VoiceCallOptions) {
    this.api = options.api;
  }

  // --- store -------------------------------------------------------------------------------------

  readonly subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  readonly getSnapshot = (): VoiceCallState => this.state;

  /** The API client changes identity with the session; the call always uses the latest one. */
  setApi(api: VoiceApi): void {
    this.api = api;
  }

  /** Playback counters, for diagnostics. */
  get playbackStats() {
    return this.player?.stats ?? null;
  }

  private dispatch(action: VoiceAction): void {
    const next = voiceReducer(this.state, action);
    if (next === this.state) return;
    this.state = next;
    this.listeners.forEach((listener) => listener());
  }

  // --- user actions (call these from click handlers) ---------------------------------------------

  /** Creates the conversation and connects. Must run inside the Start click (autoplay policy). */
  async start(scenario: Scenario): Promise<void> {
    if (this.state.phase !== "idle" && this.state.phase !== "ended") return;
    this.teardown();
    this.unlockAudio();
    this.dispatch({ type: "prepare", scenario });
    let conversationId: string;
    try {
      const conversation = await this.api.createConversation(scenario.id);
      conversationId = conversation.id;
      this.dispatch({ type: "created", conversation });
    } catch (error) {
      this.dispatch({ type: "failure", error: apiFailure(toApiError(error)) });
      return;
    }
    await this.connect(conversationId);
  }

  /** Plays the scenario's next caller line. While the receptionist is speaking, this is barge-in. */
  nextLine(): void {
    if (!canAdvance(this.state)) return;
    this.unlockAudio();
    if (receptionistSpeaking(this.state)) {
      this.dispatch({
        type: "barge_in",
        turnSeq: this.player?.playingTurn ?? this.state.streamingTurn ?? this.state.latestReceptionistTurn,
      });
      this.player?.interrupt();
    }
    this.send({ type: "next_clip" });
  }

  /** The caller hangs up. Over the socket when it is open, otherwise over REST. */
  async hangUp(): Promise<void> {
    if (!canHangUp(this.state)) return;
    this.stopClip();
    this.player?.interrupt();
    if (this.state.phase === "live" && this.socketOpen) {
      this.send({ type: "end" });
      return;
    }
    const conversation = this.state.conversation;
    if (conversation === null) return;
    this.closeSocket();
    try {
      this.dispatch({
        type: "ended_by_api",
        conversation: await this.api.endConversation(conversation.id),
      });
    } catch (error) {
      this.dispatch({ type: "failure", error: apiFailure(toApiError(error)) });
    }
  }

  /** After an unexpected close: a new ticket and socket; the server resumes with the next clip. */
  async reconnect(): Promise<void> {
    const conversation = this.state.conversation;
    if (this.state.phase !== "disconnected" || conversation === null) return;
    this.unlockAudio();
    await this.connect(conversation.id);
  }

  /** Back to scenario selection. */
  reset(): void {
    this.teardown();
    this.dispatch({ type: "reset" });
  }

  /** Releases the socket, audio and clip (unmount). The call object stays usable. */
  dispose(): void {
    this.teardown();
  }

  // --- connection --------------------------------------------------------------------------------

  private async connect(conversationId: string): Promise<void> {
    this.closeSocket();
    this.dispatch({ type: "connecting" });
    let url: string;
    try {
      const { ticket } = await this.api.issueWsTicket(conversationId);
      url = conversationSocketUrl(this.options.apiBaseUrl, conversationId, ticket);
    } catch (error) {
      this.dispatch({ type: "failure", error: apiFailure(toApiError(error)) });
      return;
    }
    if (this.state.phase !== "connecting") return; // hung up or reset meanwhile
    const generation = ++this.generation;
    const current = () => generation === this.generation;
    this.socket = this.options.createSocket(url, {
      onOpen: () => {
        if (!current()) return;
        this.socketOpen = true;
        this.dispatch({ type: "socket_open" });
      },
      onText: (text) => {
        if (current()) this.receiveText(text);
      },
      onBinary: (data) => {
        if (current()) this.receiveAudio(data);
      },
      onClose: (code, reason) => {
        if (!current()) return;
        this.socketOpen = false;
        this.socket = null;
        this.stopClip();
        this.player?.interrupt();
        this.dispatch({ type: "socket_closed", code, reason });
      },
    });
  }

  private send(command: ClientCommand): void {
    if (this.socket === null || !this.socketOpen) {
      this.dispatch({
        type: "failure",
        error: { source: "client", code: "NOT_CONNECTED", message: "The call is not connected." },
      });
      return;
    }
    this.socket.send(encodeCommand(command));
    this.dispatch({ type: "command", command });
  }

  private receiveText(text: string): void {
    const parsed = parseServerMessage(text);
    if (parsed.kind === "unknown") {
      this.dispatch({ type: "unknown_message", messageType: parsed.type });
      return;
    }
    if (parsed.kind === "invalid") {
      this.dispatch({
        type: "failure",
        error: {
          source: "socket",
          code: "INVALID_SERVER_MESSAGE",
          message: `The server sent a message this page cannot read (${parsed.reason}).`,
        },
      });
      return;
    }
    this.beforeMessage(parsed.message);
    this.dispatch({ type: "server", message: parsed.message });
    if (parsed.message.type === "ready" && parsed.message.state === "CREATED") {
      this.send({ type: "start" });
    }
  }

  /** Audio side effects of a message, applied before the state reflects it. */
  private beforeMessage(message: ServerMessage): void {
    switch (message.type) {
      case "ready":
        if (this.context === null) return;
        if (this.player === null) {
          this.player = new PcmPlayer(this.context, message.audio, (playing) =>
            this.dispatch({ type: "playback", playing }),
          );
        } else {
          this.player.setFormat(message.audio);
        }
        return;
      case "clip":
        // The caller starts talking: nothing of the receptionist may still be audible.
        this.player?.interrupt();
        void this.playClip(message.url);
        return;
      case "assistant.text":
        this.player?.beginTurn(message.turn_seq);
        return;
      case "assistant.audio_cancelled":
        this.player?.cancelTurn(message.turn_seq);
        return;
      default:
        return;
    }
  }

  private receiveAudio(data: ArrayBuffer): void {
    const frame = parseAudioFrame(data);
    if (frame === null) {
      this.dispatch({
        type: "failure",
        error: {
          source: "socket",
          code: "INVALID_AUDIO_FRAME",
          message: "The server sent an audio frame shorter than its 4-byte header.",
        },
      });
      return;
    }
    if (this.player === null) {
      if (this.audioUnavailableReported) return;
      this.audioUnavailableReported = true;
      this.dispatch({
        type: "failure",
        error: {
          source: "client",
          code: "AUDIO_UNAVAILABLE",
          message: "Receptionist audio arrived but audio playback is not available in this browser.",
        },
      });
      return;
    }
    this.player.push(frame);
  }

  // --- caller clip -------------------------------------------------------------------------------

  private async playClip(path: string): Promise<void> {
    this.stopClip();
    const token = this.clipToken;
    let blob: Blob;
    try {
      blob = await this.api.getClipAudio(path);
    } catch (error) {
      if (token === this.clipToken) {
        this.dispatch({ type: "failure", error: apiFailure(toApiError(error)) });
      }
      return;
    }
    if (token !== this.clipToken) return; // superseded by a newer clip, hang-up or reset
    const url = this.options.createObjectUrl(blob);
    this.clipUrl = url;
    this.dispatch({ type: "clip_playback", playing: true });
    try {
      await this.options.clipOutput.play(url, () => {
        if (token === this.clipToken) this.releaseClip();
      });
    } catch (error) {
      if (token !== this.clipToken) return;
      this.releaseClip();
      this.dispatch({
        type: "failure",
        error: {
          source: "client",
          code: "CLIP_PLAYBACK_FAILED",
          message: `The caller clip could not be played: ${
            error instanceof Error ? error.message : String(error)
          }`,
        },
      });
    }
  }

  private releaseClip(): void {
    if (this.clipUrl !== null) {
      this.options.revokeObjectUrl(this.clipUrl);
      this.clipUrl = null;
    }
    this.dispatch({ type: "clip_playback", playing: false });
  }

  private stopClip(): void {
    this.clipToken += 1;
    if (this.clipUrl !== null) this.options.clipOutput.stop();
    this.releaseClip();
  }

  // --- audio context -----------------------------------------------------------------------------

  /** Creates or resumes the `AudioContext` inside a user gesture, as autoplay policies require. */
  private unlockAudio(): void {
    try {
      if (this.context === null || this.context.state === "closed") {
        this.context = this.options.createAudioContext();
        this.player = null;
      }
      if (this.context.state === "suspended") {
        this.context.resume().catch((error: unknown) => this.audioFailure(error));
      }
    } catch (error) {
      this.context = null;
      this.audioFailure(error);
    }
  }

  private audioFailure(error: unknown): void {
    this.dispatch({
      type: "failure",
      error: {
        source: "client",
        code: "AUDIO_UNAVAILABLE",
        message: `Audio playback could not start: ${error instanceof Error ? error.message : String(error)}`,
      },
    });
  }

  private closeSocket(): void {
    this.generation += 1;
    this.socketOpen = false;
    const socket = this.socket;
    this.socket = null;
    socket?.close(CLOSE_NORMAL, "client closed");
  }

  private teardown(): void {
    this.closeSocket();
    this.stopClip();
    const player = this.player;
    const context = this.context;
    this.player = null;
    this.context = null;
    if (player !== null) void player.close().catch(() => {});
    else if (context !== null && context.state !== "closed") void context.close().catch(() => {});
  }

  /** Whether a socket is currently open (diagnostics and tests). */
  get connected(): boolean {
    return this.socketOpen;
  }
}

// --- browser adapters ----------------------------------------------------------------------------

/** Adapts a real `WebSocket` (binary frames as `ArrayBuffer`). */
export const browserSocket: SocketFactory = (url, handlers) => {
  const ws = new WebSocket(url);
  ws.binaryType = "arraybuffer";
  ws.onopen = () => handlers.onOpen();
  ws.onmessage = (event: MessageEvent<unknown>) => {
    if (typeof event.data === "string") handlers.onText(event.data);
    else if (event.data instanceof ArrayBuffer) handlers.onBinary(event.data);
  };
  ws.onclose = (event) => handlers.onClose(event.code, event.reason);
  return {
    send: (text) => ws.send(text),
    close: (code, reason) => {
      ws.onopen = null;
      ws.onmessage = null;
      ws.onclose = null;
      if (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN) {
        ws.close(code, reason);
      }
    },
  };
};

export function browserAudioContext(): PlaybackContext {
  return new AudioContext();
}

export const browserEnvironment: VoiceEnvironment = {
  createSocket: browserSocket,
  createAudioContext: browserAudioContext,
  createObjectUrl: (blob) => URL.createObjectURL(blob),
  revokeObjectUrl: (url) => URL.revokeObjectURL(url),
};
