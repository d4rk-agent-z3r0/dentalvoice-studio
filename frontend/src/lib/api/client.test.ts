// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import { describe, expect, it, vi } from "vitest";

import { conversation, scenario, turnResult } from "@/test/fixtures";
import { errorBody, fakeApi } from "@/test/render";

import { createApiClient, resolveApiBaseUrl } from "./client";
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
});
