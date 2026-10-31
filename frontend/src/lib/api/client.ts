// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import { ApiError, networkError, parseApiError } from "./errors";
import type {
  AnalyticsSummary,
  Appointment,
  AppointmentCreate,
  Availability,
  AvailabilityParams,
  ClinicInfo,
  Conversation,
  ConversationDetail,
  ListAppointmentsParams,
  ListConversationsParams,
  ProviderMode,
  LatencyReport,
  ListPatientsParams,
  Patient,
  PatientDetail,
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
  getConversation(
    id: string,
    options?: RequestOptions,
  ): Promise<ConversationDetail>;
  createConversation(
    scenarioId: string,
    options?: RequestOptions,
  ): Promise<Conversation>;
  startConversation(id: string, options?: RequestOptions): Promise<TurnResult>;
  sendTextTurn(
    id: string,
    text: string,
    options?: RequestOptions,
  ): Promise<TurnResult>;
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

  listPatients(
    params?: ListPatientsParams,
    options?: RequestOptions,
  ): Promise<Patient[]>;
  getPatient(id: string, options?: RequestOptions): Promise<PatientDetail>;
  getClinic(options?: RequestOptions): Promise<ClinicInfo>;
  listAppointments(
    params?: ListAppointmentsParams,
    options?: RequestOptions,
  ): Promise<Appointment[]>;
  getAvailability(
    params: AvailabilityParams,
    options?: RequestOptions,
  ): Promise<Availability>;
  /**
   * Books and confirms. `idempotencyKey` identifies one user action: sending the same key and body
   * again returns the original appointment instead of booking twice.
   */
  createAppointment(
    body: AppointmentCreate,
    idempotencyKey: string,
    options?: RequestOptions,
  ): Promise<Appointment>;
  cancelAppointment(id: string, options?: RequestOptions): Promise<Appointment>;
  getAnalyticsSummary(options?: RequestOptions): Promise<AnalyticsSummary>;
  /** `providerMode` limits the percentiles to mock or live calls; omitted means all. */
  getLatency(providerMode?: ProviderMode, options?: RequestOptions): Promise<LatencyReport>;
  /** Returns the **new** appointment; the original becomes `rescheduled`. */
  rescheduleAppointment(
    id: string,
    startsAt: string,
    options?: RequestOptions,
  ): Promise<Appointment>;
}

/** Builds `?a=1&b=2` from the defined, non-empty values; `""` when there are none. */
function queryString(
  params: Record<string, string | number | undefined>,
): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") query.set(key, String(value));
  }
  return query.size > 0 ? `?${query.toString()}` : "";
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
    extraHeaders: Record<string, string> = {},
  ): Promise<Response> {
    const headers = new Headers({ ...extraHeaders, Accept: accept });
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
      const error = parseApiError(
        response.status,
        payload,
        response.headers.get("X-Request-ID"),
      );
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
    extraHeaders: Record<string, string> = {},
  ): Promise<T> {
    const response = await send(
      method,
      path,
      body,
      "application/json",
      requestOptions,
      extraHeaders,
    );
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
    listScenarios: (opts) =>
      request<Scenario[]>("GET", "/api/v1/scenarios", undefined, opts),
    listConversations: (params = {}, opts) => {
      const query = new URLSearchParams();
      if (params.state) query.set("state", params.state);
      if (params.limit !== undefined) query.set("limit", String(params.limit));
      const suffix = query.size > 0 ? `?${query.toString()}` : "";
      return request<Conversation[]>(
        "GET",
        `/api/v1/conversations${suffix}`,
        undefined,
        opts,
      );
    },
    getConversation: (conversationId, opts) =>
      request<ConversationDetail>(
        "GET",
        `/api/v1/conversations/${id(conversationId)}`,
        undefined,
        opts,
      ),
    createConversation: (scenarioId, opts) =>
      request<Conversation>(
        "POST",
        "/api/v1/conversations",
        { scenario_id: scenarioId },
        opts,
      ),
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
          message:
            "The server announced a caller clip outside the clip endpoint; it was not fetched.",
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

    listPatients: (params = {}, opts) =>
      request<Patient[]>(
        "GET",
        `/api/v1/patients${queryString({
          q: params.q?.trim(),
          status: params.status,
          limit: params.limit,
          offset: params.offset,
        })}`,
        undefined,
        opts,
      ),
    getPatient: (patientId, opts) =>
      request<PatientDetail>(
        "GET",
        `/api/v1/patients/${id(patientId)}`,
        undefined,
        opts,
      ),
    getClinic: (opts) =>
      request<ClinicInfo>("GET", "/api/v1/clinic", undefined, opts),
    listAppointments: (params = {}, opts) =>
      request<Appointment[]>(
        "GET",
        `/api/v1/appointments${queryString({
          from: params.from,
          to: params.to,
          status: params.status,
          limit: params.limit,
        })}`,
        undefined,
        opts,
      ),
    getAvailability: (params, opts) =>
      request<Availability>(
        "GET",
        `/api/v1/availability${queryString({
          appointment_type_id: params.appointmentTypeId,
          date: params.date,
          days: params.days,
        })}`,
        undefined,
        opts,
      ),
    createAppointment: (body, idempotencyKey, opts) =>
      request<Appointment>("POST", "/api/v1/appointments", body, opts, {
        "Idempotency-Key": idempotencyKey,
      }),
    cancelAppointment: (appointmentId, opts) =>
      request<Appointment>(
        "POST",
        `/api/v1/appointments/${id(appointmentId)}/cancel`,
        undefined,
        opts,
      ),
    getAnalyticsSummary: (opts) =>
      request<AnalyticsSummary>("GET", "/api/v1/analytics/summary", undefined, opts),
    getLatency: (providerMode, opts) =>
      request<LatencyReport>(
        "GET",
        `/api/v1/analytics/latency${queryString({ provider_mode: providerMode })}`,
        undefined,
        opts,
      ),
    rescheduleAppointment: (appointmentId, startsAt, opts) =>
      request<Appointment>(
        "POST",
        `/api/v1/appointments/${id(appointmentId)}/reschedule`,
        { starts_at: startsAt },
        opts,
      ),
  };
}
