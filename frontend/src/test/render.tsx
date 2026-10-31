// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import { render, type RenderResult } from "@testing-library/react";
import type { ReactElement } from "react";
import { vi } from "vitest";

import { ApiProvider } from "@/lib/api/ApiProvider";
import { AuthProvider } from "@/lib/auth/AuthProvider";
import { createSessionStore, type SessionStore } from "@/lib/auth/session-store";

import { makeToken } from "./fixtures";

export interface RecordedRequest {
  method: string;
  path: string;
  search: string;
  headers: Headers;
  body: unknown;
}

type Reply = { status: number; body?: unknown } | Promise<{ status: number; body?: unknown }>;
export type Route = (request: RecordedRequest) => Reply;

/**
 * A fake `fetch` keyed by `"METHOD /path"` (query string excluded; it is recorded in `search`).
 * Unknown routes fail the test loudly instead of returning something plausible.
 */
export function fakeApi(routes: Record<string, Route | { status: number; body?: unknown }>) {
  const requests: RecordedRequest[] = [];
  const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    const request: RecordedRequest = {
      method: init?.method ?? "GET",
      path: url.pathname,
      search: url.search,
      headers: new Headers(init?.headers),
      body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined,
    };
    requests.push(request);
    const route = routes[`${request.method} ${request.path}`];
    if (!route) throw new Error(`Unexpected request ${request.method} ${request.path}`);
    const reply = await (typeof route === "function" ? route(request) : route);
    return new Response(reply.body === undefined ? null : JSON.stringify(reply.body), {
      status: reply.status,
      headers: { "Content-Type": "application/json" },
    });
  });
  return { fetchImpl: fetchImpl as unknown as typeof fetch, requests, mock: fetchImpl };
}

export function memoryStorage(): Storage {
  const data = new Map<string, string>();
  return {
    get length() {
      return data.size;
    },
    clear: () => data.clear(),
    getItem: (key) => data.get(key) ?? null,
    key: (index) => [...data.keys()][index] ?? null,
    removeItem: (key) => void data.delete(key),
    setItem: (key, value) => void data.set(key, String(value)),
  };
}

export function signedInStore(token = makeToken()): SessionStore {
  const storage = memoryStorage();
  const store = createSessionStore(() => storage);
  store.setSession(token, "developer_token");
  return store;
}

export function renderWithProviders(
  ui: ReactElement,
  {
    fetchImpl,
    store = signedInStore(),
  }: { fetchImpl?: typeof fetch; store?: SessionStore } = {},
): RenderResult & { store: SessionStore } {
  const result = render(
    <AuthProvider store={store}>
      <ApiProvider fetchImpl={fetchImpl}>{ui}</ApiProvider>
    </AuthProvider>,
  );
  return { ...result, store };
}

export function errorBody(code: string, message: string, requestId = "req-123") {
  return { error: { code, message, request_id: requestId } };
}
