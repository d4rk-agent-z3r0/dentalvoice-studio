// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import { ApiError, networkError, parseApiError } from "./errors";
import type {
  Conversation,
  ConversationDetail,
  ListConversationsParams,
  Scenario,
  TurnResult,
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
}

type Method = "GET" | "POST";

export function createApiClient(options: ApiClientOptions): ApiClient {
  const baseUrl = resolveApiBaseUrl(options.baseUrl);
  const fetchImpl = options.fetchImpl ?? ((input, init) => fetch(input, init));

  async function request<T>(
    method: Method,
    path: string,
    body: unknown,
    { signal }: RequestOptions = {},
  ): Promise<T> {
    const headers = new Headers({ Accept: "application/json" });
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

    const payload: unknown = await response.json().catch(() => undefined);
    if (!response.ok) {
      const error = parseApiError(response.status, payload, response.headers.get("X-Request-ID"));
      if (error.isUnauthorized) options.onUnauthorized?.(error);
      throw error;
    }
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
  };
}
