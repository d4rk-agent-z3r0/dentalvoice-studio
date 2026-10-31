// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
"use client";

import { createContext, useContext, useMemo, type ReactNode } from "react";

import { useAuth } from "@/lib/auth/AuthProvider";

import { createApiClient, resolveApiBaseUrl, type ApiClient } from "./client";

/** Inlined by Next.js at build time; must be referenced literally. */
export const API_BASE_URL = resolveApiBaseUrl(process.env.NEXT_PUBLIC_API_BASE_URL);

const ApiClientContext = createContext<ApiClient | null>(null);

/**
 * Provides the typed API client. The bearer token is read from the auth context on every request,
 * and a 401 ends the session so the sign-in screen appears with the server's reason.
 */
export function ApiProvider({
  children,
  fetchImpl,
}: {
  children: ReactNode;
  /** Injected in tests. */
  fetchImpl?: typeof fetch;
}) {
  const { getToken, rejectSession } = useAuth();
  const client = useMemo(
    () =>
      createApiClient({
        baseUrl: API_BASE_URL,
        getToken,
        onUnauthorized: rejectSession,
        fetchImpl,
      }),
    [getToken, rejectSession, fetchImpl],
  );
  return <ApiClientContext.Provider value={client}>{children}</ApiClientContext.Provider>;
}

export function useApiClient(): ApiClient {
  const client = useContext(ApiClientContext);
  if (!client) throw new Error("useApiClient must be used inside <ApiProvider>.");
  return client;
}
