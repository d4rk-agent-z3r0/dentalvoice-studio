// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import { ApiError, networkError, parseApiError } from "./errors";
import type {
  Conversation,
  ConversationDetail,
  ListConversationsParams,
  Scenario,
  TurnResult,
  WsTicket,
} from "./types";

/** Public, non-secret value inlined at build time (see `frontend/Dockerfile`). */
export const DEFAULT_API_BASE_URL = "http://localhost:8000";

export function resolveApiBaseUrl(value: string | undefined): string {
  const trimmed = value?.trim();
  return (trimmed ? trimmed : DEFAULT_API_BASE_URL).replace(/\/+$/, "");
}

export interface ApiClientOptions {
  baseUrl: string;
  /** Returns the current access token, or `null` when signed out. Called on every request. */
  getToken: () => string | null;
  /** Called once per 401 response, before the error is thrown (e.g. to end the session). */
  onUnauthorized?: (error: ApiError) => void;
  fetchImpl?: typeof fetch;
}

export interface RequestOptions {
  signal?: AbortSignal;
}

export interface ApiClient {
  listScenarios(options?: RequestOptions): Promise<Scenario[]>;
  listConversations(
    params?: ListConversationsParams,
    options?: RequestOptions,
  ): Promise<Conversation[]>;
  getConversation(id: string, options?: RequestOptions): Promise<ConversationDetail>;
  createConversation(scenarioId: string, options?: RequestOptions): Promise<Conversation>;
  startConversation(id: string, options?: RequestOptions): Promise<TurnResult>;
  sendTextTurn(id: string, text: string, options?: RequestOptions): Promise<TurnResult>;
  endConversation(id: string, options?: RequestOptions): Promise<Conversation>;
  /** Single-use WebSocket admission ticket (ADR-0006). */
  issueWsTicket(id: string, options?: RequestOptions): Promise<WsTicket>;
  /**
   * Downloads a synthetic caller clip announced by the voice socket. Only paths under
   * `/api/v1/audio/clips/` are accepted, so the bearer token is never sent anywhere else.
   */
  getClipAudio(path: string, options?: RequestOptions): Promise<Blob>;
  /**
   * Whether the backend accepts typed caller turns (`false` in production, where they are a
   * `403`). Probed without side effects; see `TEXT_TURN_PROBE_ID`.
   */
  textTurnsEnabled(options?: RequestOptions): Promise<boolean>;
}

/** Caller clip URLs as the voice socket sends them (`clip.url`). */
export const CLIP_PATH = /^\/api\/v1\/audio\/clips\/[a-z]{1,2}-\d{2}$/;

/**
 * A conversation id that cannot exist (UUIDv7 ids are never all zeros). Posting a typed turn to it
 * is refused with `403 FORBIDDEN` when typed turns are disabled (checked first) and `404
 * NOT_FOUND` otherwise; nothing is written either way. The backend has no capability endpoint.
 */
export const TEXT_TURN_PROBE_ID = "00000000-0000-0000-0000-000000000000";

type Method = "GET" | "POST";

export function createApiClient(options: ApiClientOptions): ApiClient {
  const baseUrl = resolveApiBaseUrl(options.baseUrl);
  const fetchImpl = options.fetchImpl ?? ((input, init) => fetch(input, init));

  async function send(
    method: Method,
    path: string,
    body: unknown,
    accept: string,
    { signal }: RequestOptions = {},
  ): Promise<Response> {
    const headers = new Headers({ Accept: accept });
    const token = options.getToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    if (body !== undefined) headers.set("Content-Type", "application/json");

    let response: Response;
    try {
      response = await fetchImpl(`${baseUrl}${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal,
        cache: "no-store",
        credentials: "omit",
      });
    } catch (cause) {
      if (signal?.aborted) throw cause;
      throw networkError(cause);
    }
    if (!response.ok) {
      const payload: unknown = await response.json().catch(() => undefined);
      const error = parseApiError(response.status, payload, response.headers.get("X-Request-ID"));
      if (error.isUnauthorized) options.onUnauthorized?.(error);
      throw error;
    }
    return response;
  }

  async function request<T>(
    method: Method,
    path: string,
    body: unknown,
    requestOptions: RequestOptions = {},
  ): Promise<T> {
    const response = await send(method, path, body, "application/json", requestOptions);
    const payload: unknown = await response.json().catch(() => undefined);
    if (payload === undefined) {
      throw new ApiError({
        status: response.status,
        code: "UNEXPECTED_RESPONSE",
        message: "The server returned a response that is not JSON.",
        requestId: response.headers.get("X-Request-ID"),
      });
    }
    // The backend validates every response with Pydantic `response_model`s; the shapes in
    // `types.ts` mirror those models.
    return payload as T;
  }

  const id = (value: string) => encodeURIComponent(value);

  return {
    listScenarios: (opts) => request<Scenario[]>("GET", "/api/v1/scenarios", undefined, opts),
    listConversations: (params = {}, opts) => {
      const query = new URLSearchParams();
      if (params.state) query.set("state", params.state);
      if (params.limit !== undefined) query.set("limit", String(params.limit));
      const suffix = query.size > 0 ? `?${query.toString()}` : "";
      return request<Conversation[]>("GET", `/api/v1/conversations${suffix}`, undefined, opts);
    },
    getConversation: (conversationId, opts) =>
      request<ConversationDetail>(
        "GET",
        `/api/v1/conversations/${id(conversationId)}`,
        undefined,
        opts,
      ),
    createConversation: (scenarioId, opts) =>
      request<Conversation>("POST", "/api/v1/conversations", { scenario_id: scenarioId }, opts),
    startConversation: (conversationId, opts) =>
      request<TurnResult>(
        "POST",
        `/api/v1/conversations/${id(conversationId)}/start`,
        undefined,
        opts,
      ),
    sendTextTurn: (conversationId, text, opts) =>
      request<TurnResult>(
        "POST",
        `/api/v1/conversations/${id(conversationId)}/turns`,
        { text },
        opts,
      ),
    endConversation: (conversationId, opts) =>
      request<Conversation>(
        "POST",
        `/api/v1/conversations/${id(conversationId)}/end`,
        undefined,
        opts,
      ),
    issueWsTicket: (conversationId, opts) =>
      request<WsTicket>(
        "POST",
        `/api/v1/conversations/${id(conversationId)}/ws-ticket`,
        undefined,
        opts,
      ),
    async getClipAudio(path, opts) {
      if (!CLIP_PATH.test(path)) {
        throw new ApiError({
          status: 0,
          code: "UNEXPECTED_RESPONSE",
          message: "The server announced a caller clip outside the clip endpoint; it was not fetched.",
        });
      }
      const response = await send("GET", path, undefined, "audio/wav", opts);
      return response.blob();
    },
    async textTurnsEnabled(opts) {
      try {
        await request<TurnResult>(
          "POST",
          `/api/v1/conversations/${TEXT_TURN_PROBE_ID}/turns`,
          { text: "capability probe" },
          opts,
        );
        return true;
      } catch (error) {
        if (!(error instanceof ApiError)) throw error;
        if (error.status === 404 && error.code === "NOT_FOUND") return true;
        if (error.status === 403) return false;
        throw error;
      }
    },
  };
}
