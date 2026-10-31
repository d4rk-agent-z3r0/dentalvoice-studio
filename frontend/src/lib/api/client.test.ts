// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import { describe, expect, it, vi } from "vitest";

import {
  SECOND_CLINIC_ID,
  authMe,
  authTokenResponse,
  conversation,
  scenario,
  turnResult,
} from "@/test/fixtures";
import { errorBody, fakeApi } from "@/test/render";

import { TEXT_TURN_PROBE_ID, createApiClient, resolveApiBaseUrl } from "./client";
import { ApiError, parseApiError } from "./errors";

const BASE = "http://api.test";

describe("resolveApiBaseUrl", () => {
  it("uses the configured value without trailing slashes", () => {
    expect(resolveApiBaseUrl("http://localhost:8010/")).toBe("http://localhost:8010");
  });

  it("falls back to the documented default when unset or blank", () => {
    expect(resolveApiBaseUrl(undefined)).toBe("http://localhost:8000");
    expect(resolveApiBaseUrl("  ")).toBe("http://localhost:8000");
  });
});

describe("parseApiError", () => {
  it("reads code, message, request id and validation details from the contract body", () => {
    const error = parseApiError(400, {
      error: {
        code: "VALIDATION_ERROR",
        message: "The request is invalid.",
        request_id: "rid-1",
        details: [{ loc: ["query", "state"], msg: "Input should be 'CREATED'" }],
      },
    });
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 400,
      code: "VALIDATION_ERROR",
      message: "The request is invalid.",
      requestId: "rid-1",
      details: [{ loc: ["query", "state"], msg: "Input should be 'CREATED'" }],
    });
  });

  it("never invents a code for a body outside the contract", () => {
    const error = parseApiError(502, "<html>Bad gateway</html>", "rid-header");
    expect(error.code).toBe("UNEXPECTED_RESPONSE");
    expect(error.status).toBe(502);
    expect(error.requestId).toBe("rid-header");
  });
});

describe("createApiClient", () => {
  it("attaches the current bearer token to every request", async () => {
    const api = fakeApi({ "GET /api/v1/scenarios": { status: 200, body: [scenario()] } });
    let token: string | null = "token-1";
    const client = createApiClient({ baseUrl: BASE, getToken: () => token, fetchImpl: api.fetchImpl });

    await client.listScenarios();
    token = "token-2";
    await client.listScenarios();

    expect(api.requests.map((r) => r.headers.get("Authorization"))).toEqual([
      "Bearer token-1",
      "Bearer token-2",
    ]);
  });

  it("sends no Authorization header when signed out", async () => {
    const api = fakeApi({ "GET /api/v1/scenarios": { status: 200, body: [] } });
    const client = createApiClient({ baseUrl: BASE, getToken: () => null, fetchImpl: api.fetchImpl });
    await client.listScenarios();
    expect(api.requests[0].headers.has("Authorization")).toBe(false);
  });

  it("builds list queries and request bodies the backend expects", async () => {
    const api = fakeApi({
      "GET /api/v1/conversations": { status: 200, body: [conversation()] },
      "POST /api/v1/conversations": { status: 201, body: conversation() },
      "POST /api/v1/conversations/c-1/turns": { status: 200, body: turnResult() },
    });
    const client = createApiClient({ baseUrl: BASE, getToken: () => "t", fetchImpl: api.fetchImpl });

    await client.listConversations({ state: "COMPLETED", limit: 50 });
    await client.listConversations();
    await client.createConversation("s-1");
    await client.sendTextTurn("c-1", "Hello");

    expect(api.requests[0].search).toBe("?state=COMPLETED&limit=50");
    expect(api.requests[1].search).toBe("");
    expect(api.requests[2].body).toEqual({ scenario_id: "s-1" });
    expect(api.requests[2].headers.get("Content-Type")).toBe("application/json");
    expect(api.requests[3].body).toEqual({ text: "Hello" });
  });

  it("throws an ApiError with the server's code, message and request id", async () => {
    const api = fakeApi({
      "POST /api/v1/conversations/c-1/end": {
        status: 409,
        body: errorBody("CONVERSATION_CLOSED", "This conversation has ended.", "rid-409"),
      },
    });
    const client = createApiClient({ baseUrl: BASE, getToken: () => "t", fetchImpl: api.fetchImpl });

    const error = await client.endConversation("c-1").catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 409,
      code: "CONVERSATION_CLOSED",
      message: "This conversation has ended.",
      requestId: "rid-409",
    });
  });

  it("reports a 401 to onUnauthorized before throwing", async () => {
    const api = fakeApi({
      "GET /api/v1/scenarios": {
        status: 401,
        body: errorBody("AUTH_INVALID", "The access token has expired."),
      },
    });
    const onUnauthorized = vi.fn();
    const client = createApiClient({
      baseUrl: BASE,
      getToken: () => "t",
      onUnauthorized,
      fetchImpl: api.fetchImpl,
    });

    await expect(client.listScenarios()).rejects.toMatchObject({ code: "AUTH_INVALID" });
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
    expect(onUnauthorized.mock.calls[0][0]).toMatchObject({ status: 401, code: "AUTH_INVALID" });
  });

  it("does not treat other errors as unauthorized", async () => {
    const api = fakeApi({
      "GET /api/v1/scenarios": { status: 403, body: errorBody("FORBIDDEN", "No.") },
    });
    const onUnauthorized = vi.fn();
    const client = createApiClient({
      baseUrl: BASE,
      getToken: () => "t",
      onUnauthorized,
      fetchImpl: api.fetchImpl,
    });
    await expect(client.listScenarios()).rejects.toMatchObject({ status: 403 });
    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  it("turns an unreachable server into NETWORK_ERROR", async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    const client = createApiClient({ baseUrl: BASE, getToken: () => "t", fetchImpl });
    await expect(client.listScenarios()).rejects.toMatchObject({
      code: "NETWORK_ERROR",
      status: 0,
    });
  });

  it("passes aborts through instead of reporting a network error", async () => {
    const controller = new AbortController();
    const abort = new DOMException("Aborted", "AbortError");
    const fetchImpl = vi.fn().mockImplementation(() => {
      controller.abort();
      return Promise.reject(abort);
    });
    const client = createApiClient({ baseUrl: BASE, getToken: () => "t", fetchImpl });
    await expect(client.listScenarios({ signal: controller.signal })).rejects.toBe(abort);
  });

  it("URL-encodes path ids", async () => {
    const api = fakeApi({ "GET /api/v1/conversations/a%2Fb": { status: 200, body: {} } });
    const client = createApiClient({ baseUrl: BASE, getToken: () => "t", fetchImpl: api.fetchImpl });
    await client.getConversation("a/b");
    expect(api.requests[0].path).toBe("/api/v1/conversations/a%2Fb");
  });

  it("builds patient queries, omitting blank search terms", async () => {
    const api = fakeApi({
      "GET /api/v1/patients": { status: 200, body: [] },
      "GET /api/v1/patients/p%2F1": { status: 200, body: {} },
    });
    const client = createApiClient({ baseUrl: BASE, getToken: () => "t", fetchImpl: api.fetchImpl });

    await client.listPatients();
    await client.listPatients({ q: "  ", status: "archived", limit: 26, offset: 0 });
    await client.listPatients({ q: " Ava Lind ", offset: 25 });
    await client.getPatient("p/1");

    expect(api.requests.map((r) => r.search)).toEqual([
      "",
      "?status=archived&limit=26&offset=0",
      "?q=Ava+Lind&offset=25",
      "",
    ]);
    expect(api.requests[3].path).toBe("/api/v1/patients/p%2F1");
  });

  it("sends booking writes with the Idempotency-Key header and the documented bodies", async () => {
    const api = fakeApi({
      "GET /api/v1/clinic": { status: 200, body: {} },
      "GET /api/v1/appointments": { status: 200, body: [] },
      "GET /api/v1/availability": { status: 200, body: {} },
      "POST /api/v1/appointments": { status: 201, body: {} },
      "POST /api/v1/appointments/a-1/cancel": { status: 200, body: {} },
      "POST /api/v1/appointments/a-1/reschedule": { status: 201, body: {} },
    });
    const client = createApiClient({ baseUrl: BASE, getToken: () => "t", fetchImpl: api.fetchImpl });
    const body = {
      patient_id: "p",
      appointment_type_id: "t",
      dentist_id: "d",
      starts_at: "2030-01-07T09:00:00Z",
      conversation_id: null,
    };

    await client.getClinic();
    await client.listAppointments({ from: "2030-01-07", to: "2030-01-08", status: "confirmed" });
    await client.getAvailability({ appointmentTypeId: "t", date: "2030-01-07", days: 2 });
    await client.createAppointment(body, "key-12345678");
    await client.cancelAppointment("a-1");
    await client.rescheduleAppointment("a-1", "2030-01-07T10:00:00Z");

    const [, list, slots, create, cancel, reschedule] = api.requests;
    expect(list.search).toBe("?from=2030-01-07&to=2030-01-08&status=confirmed");
    expect(slots.search).toBe("?appointment_type_id=t&date=2030-01-07&days=2");
    expect(create.headers.get("Idempotency-Key")).toBe("key-12345678");
    expect(create.headers.get("Authorization")).toBe("Bearer t");
    expect(create.body).toEqual(body);
    expect(cancel.body).toBeUndefined();
    expect(cancel.headers.has("Idempotency-Key")).toBe(false);
    expect(reschedule.body).toEqual({ starts_at: "2030-01-07T10:00:00Z" });
  });

  it("requests analytics, with the provider mode only when one is chosen", async () => {
    const api = fakeApi({
      "GET /api/v1/analytics/summary": { status: 200, body: {} },
      "GET /api/v1/analytics/latency": { status: 200, body: {} },
    });
    const client = createApiClient({ baseUrl: BASE, getToken: () => "t", fetchImpl: api.fetchImpl });
    await client.getAnalyticsSummary();
    await client.getLatency();
    await client.getLatency("mock");
    expect(api.requests.map((r) => `${r.path}${r.search}`)).toEqual([
      "/api/v1/analytics/summary",
      "/api/v1/analytics/latency",
      "/api/v1/analytics/latency?provider_mode=mock",
    ]);
  });
});

describe("auth endpoints", () => {
  const credentials = () => ({
    email: "demo.staff@example.com",
    // Generated per test: no password-like literal is committed.
    password: `pw-${crypto.randomUUID()}`,
  });

  it("logs in without an Authorization header, even while a token is held", async () => {
    const response = authTokenResponse();
    const api = fakeApi({ "POST /api/v1/auth/login": { status: 200, body: response } });
    const client = createApiClient({
      baseUrl: BASE,
      getToken: () => "stale-token",
      fetchImpl: api.fetchImpl,
    });
    const body = credentials();

    await expect(client.login(body)).resolves.toEqual(response);

    expect(api.requests[0].headers.has("Authorization")).toBe(false);
    expect(api.requests[0].body).toEqual(body);
    expect(api.requests[0].search).toBe("");
  });

  it("does not report a failed login to onUnauthorized", async () => {
    const api = fakeApi({
      "POST /api/v1/auth/login": {
        status: 401,
        body: errorBody("AUTH_FAILED", "Email or password is incorrect.", "rid-login"),
      },
    });
    const onUnauthorized = vi.fn();
    const client = createApiClient({
      baseUrl: BASE,
      getToken: () => null,
      onUnauthorized,
      fetchImpl: api.fetchImpl,
    });

    await expect(client.login(credentials())).rejects.toMatchObject({
      status: 401,
      code: "AUTH_FAILED",
      requestId: "rid-login",
    });
    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  it("reads the wait after a rate-limited login from the body, then the header", async () => {
    const limited = (body: unknown, headers: Record<string, string> = {}) => {
      const fetchImpl = vi.fn(
        async () =>
          new Response(JSON.stringify(body), {
            status: 429,
            headers: { "Content-Type": "application/json", ...headers },
          }),
      ) as unknown as typeof fetch;
      return createApiClient({ baseUrl: BASE, getToken: () => null, fetchImpl });
    };
    const fromBody = {
      error: {
        code: "RATE_LIMITED",
        message: "Too many attempts.",
        request_id: "r",
        retry_after_seconds: 42,
      },
    };

    await expect(limited(fromBody, { "Retry-After": "7" }).login(credentials())).rejects.toMatchObject({
      status: 429,
      retryAfterSeconds: 42,
    });
    await expect(
      limited(errorBody("RATE_LIMITED", "Too many attempts."), { "Retry-After": "7" }).login(
        credentials(),
      ),
    ).rejects.toMatchObject({ retryAfterSeconds: 7 });
    await expect(
      limited(errorBody("RATE_LIMITED", "Too many attempts.")).login(credentials()),
    ).rejects.toMatchObject({ retryAfterSeconds: null });
  });

  it("switches clinic with the bearer token and only the clinic id in the body", async () => {
    const api = fakeApi({
      "POST /api/v1/auth/switch-clinic": { status: 200, body: authTokenResponse() },
    });
    const client = createApiClient({ baseUrl: BASE, getToken: () => "t", fetchImpl: api.fetchImpl });
    await client.switchClinic(SECOND_CLINIC_ID);
    expect(api.requests[0].headers.get("Authorization")).toBe("Bearer t");
    expect(api.requests[0].body).toEqual({ clinic_id: SECOND_CLINIC_ID });
  });

  it("treats a 401 from switch-clinic or me as an ended session", async () => {
    const api = fakeApi({
      "POST /api/v1/auth/switch-clinic": { status: 401, body: errorBody("AUTH_INVALID", "Expired.") },
      "GET /api/v1/auth/me": { status: 401, body: errorBody("AUTH_INVALID", "Expired.") },
    });
    const onUnauthorized = vi.fn();
    const client = createApiClient({
      baseUrl: BASE,
      getToken: () => "t",
      onUnauthorized,
      fetchImpl: api.fetchImpl,
    });
    await expect(client.switchClinic(SECOND_CLINIC_ID)).rejects.toMatchObject({ status: 401 });
    await expect(client.me()).rejects.toMatchObject({ status: 401 });
    expect(onUnauthorized).toHaveBeenCalledTimes(2);
  });

  it("reads who the token is for", async () => {
    const me = authMe();
    const api = fakeApi({ "GET /api/v1/auth/me": { status: 200, body: me } });
    const client = createApiClient({ baseUrl: BASE, getToken: () => "t", fetchImpl: api.fetchImpl });
    await expect(client.me()).resolves.toEqual(me);
    expect(api.requests[0].headers.get("Authorization")).toBe("Bearer t");
  });
});

describe("voice endpoints", () => {
  const client = (routes: Parameters<typeof fakeApi>[0]) => {
    const api = fakeApi(routes);
    return {
      api,
      client: createApiClient({ baseUrl: BASE, getToken: () => "t", fetchImpl: api.fetchImpl }),
    };
  };

  it("issues a WebSocket ticket for the conversation", async () => {
    const { api, client: c } = client({
      "POST /api/v1/conversations/c-1/ws-ticket": {
        status: 200,
        body: { ticket: "tkt_abc", expires_in: 60 },
      },
    });
    await expect(c.issueWsTicket("c-1")).resolves.toEqual({ ticket: "tkt_abc", expires_in: 60 });
    expect(api.requests[0].headers.get("Authorization")).toBe("Bearer t");
  });

  it("downloads a caller clip with the bearer token", async () => {
    const { api, client: c } = client({
      "GET /api/v1/audio/clips/a-01": { status: 200, body: "RIFF" },
    });
    const blob = await c.getClipAudio("/api/v1/audio/clips/a-01");
    expect(blob.size).toBeGreaterThan(0);
    expect(api.requests[0].headers.get("Authorization")).toBe("Bearer t");
    expect(api.requests[0].headers.get("Accept")).toBe("audio/wav");
  });

  it("refuses to send the token to a clip URL outside the clip endpoint", async () => {
    const { api, client: c } = client({});
    for (const path of [
      "https://evil.example.com/api/v1/audio/clips/a-01",
      "//evil.example.com/api/v1/audio/clips/a-01",
      "/api/v1/conversations",
      "/api/v1/audio/clips/../../conversations",
    ]) {
      await expect(c.getClipAudio(path)).rejects.toMatchObject({ code: "UNEXPECTED_RESPONSE" });
    }
    expect(api.requests).toHaveLength(0);
  });

  it("reports a clip 404 with the server's code", async () => {
    const { client: c } = client({
      "GET /api/v1/audio/clips/z-99": {
        status: 404,
        body: errorBody("NOT_FOUND", "Clip not found."),
      },
    });
    await expect(c.getClipAudio("/api/v1/audio/clips/z-99")).rejects.toMatchObject({
      status: 404,
      code: "NOT_FOUND",
    });
  });

  it("probes typed turns: 404 on the impossible id means enabled, 403 means disabled", async () => {
    const path = `POST /api/v1/conversations/${TEXT_TURN_PROBE_ID}/turns`;
    const enabled = client({ [path]: { status: 404, body: errorBody("NOT_FOUND", "Not found.") } });
    await expect(enabled.client.textTurnsEnabled()).resolves.toBe(true);
    expect(enabled.api.requests[0].body).toEqual({ text: "capability probe" });

    const disabled = client({ [path]: { status: 403, body: errorBody("FORBIDDEN", "Disabled.") } });
    await expect(disabled.client.textTurnsEnabled()).resolves.toBe(false);

    const broken = client({
      [path]: { status: 503, body: errorBody("PROVIDER_UNAVAILABLE", "Down.") },
    });
    await expect(broken.client.textTurnsEnabled()).rejects.toMatchObject({ status: 503 });
  });
});
