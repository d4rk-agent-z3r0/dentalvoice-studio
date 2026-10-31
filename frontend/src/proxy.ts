// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import { NextResponse, type NextRequest } from "next/server";

import { resolveApiBaseUrl } from "@/lib/api/client";
import { buildContentSecurityPolicy, createNonce } from "@/lib/security/headers";

/** Inlined at build time, exactly as the browser client resolves it. */
const API_BASE_URL = resolveApiBaseUrl(process.env.NEXT_PUBLIC_API_BASE_URL);

/**
 * Sets a nonce-based Content-Security-Policy on every page, the documented Next.js 16 way: the
 * policy goes on the request (Next.js reads the nonce from it while rendering and puts it on its
 * own scripts and styles) and on the response (the browser enforces it). Pages render per request
 * for this; see `app/layout.tsx`.
 */
export function proxy(request: NextRequest) {
  const policy = buildContentSecurityPolicy({
    nonce: createNonce(),
    apiBaseUrl: API_BASE_URL,
    development: process.env.NODE_ENV === "development",
  });

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("Content-Security-Policy", policy);
  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", policy);
  return response;
}

export const config = {
  matcher: [
    {
      // Documents only: static files carry no inline code, and prefetches are not documents.
      source: "/((?!_next/static|_next/image|favicon.ico).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
