// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
/**
 * Browser security headers. The fixed ones are sent for every path from `next.config.ts`; the
 * Content-Security-Policy carries a per-request nonce and is set by `src/proxy.ts`, following the
 * Next.js 16 guide (`node_modules/next/dist/docs/01-app/02-guides/content-security-policy.md`).
 *
 * Kept free of Next.js imports so `next.config.ts`, the proxy and unit tests can all load it.
 */

export interface SecurityHeader {
  key: string;
  value: string;
}

/** Sent on every response, documents and static assets alike. */
export const SECURITY_HEADERS: SecurityHeader[] = [
  // Never guess a content type: a clip or JSON body is never run as a script or stylesheet.
  { key: "X-Content-Type-Options", value: "nosniff" },
  // URLs (with ids in their paths) are not leaked to the API or any other origin.
  { key: "Referrer-Policy", value: "no-referrer" },
  // The app never records: caller speech comes only from synthetic clips.
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  // For browsers without CSP `frame-ancestors`.
  { key: "X-Frame-Options", value: "DENY" },
];

/** 128 random bits, base64: a fresh value for every page request. */
export function createNonce(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return btoa(String.fromCharCode(...bytes));
}

/**
 * The API origin and its WebSocket counterpart (`http` → `ws`, `https` → `wss`), as the client
 * and the voice socket derive them from `NEXT_PUBLIC_API_BASE_URL`. Origins only: a path in the
 * base URL is not part of a CSP source match.
 */
export function apiConnectSources(apiBaseUrl: string): [http: string, ws: string] {
  let url: URL;
  try {
    url = new URL(apiBaseUrl);
  } catch {
    throw new Error(`NEXT_PUBLIC_API_BASE_URL is not a valid URL: ${JSON.stringify(apiBaseUrl)}`);
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error(`NEXT_PUBLIC_API_BASE_URL must be http or https, not ${url.protocol}`);
  }
  const ws = url.protocol === "https:" ? "wss:" : "ws:";
  return [url.origin, `${ws}//${url.host}`];
}

export interface CspOptions {
  nonce: string;
  /** The resolved `NEXT_PUBLIC_API_BASE_URL`. */
  apiBaseUrl: string;
  /** `next dev` only: React needs `eval` for debugging and the dev overlay injects styles. */
  development: boolean;
}

const NONCE_PATTERN = /^[A-Za-z0-9+/_-]+={0,2}$/;

export function buildContentSecurityPolicy({ nonce, apiBaseUrl, development }: CspOptions): string {
  if (!NONCE_PATTERN.test(nonce)) throw new Error("The CSP nonce must be a base64 value.");
  const [apiOrigin, apiSocketOrigin] = apiConnectSources(apiBaseUrl);
  const nonceSource = `'nonce-${nonce}'`;

  const policy: Array<[string, ...string[]]> = [
    ["default-src", "'self'"],
    // Next.js puts the nonce on its scripts; 'strict-dynamic' lets them load their chunks.
    [
      "script-src",
      "'self'",
      nonceSource,
      "'strict-dynamic'",
      ...(development ? ["'unsafe-eval'"] : []),
    ],
    // In development a nonce would make browsers ignore 'unsafe-inline', so it is left out there.
    ["style-src", "'self'", ...(development ? ["'unsafe-inline'"] : [nonceSource])],
    ["img-src", "'self'"],
    ["font-src", "'self'"],
    // REST calls and the voice WebSocket go to the API origin.
    ["connect-src", "'self'", apiOrigin, apiSocketOrigin],
    // The simulator plays caller clips from blob: URLs of downloaded WAVs.
    ["media-src", "'self'", "blob:"],
    ["object-src", "'none'"],
    ["base-uri", "'none'"],
    ["form-action", "'self'"],
    ["frame-ancestors", "'none'"],
  ];
  // Upgrading only makes sense when the API is served over HTTPS; on a plain-HTTP local setup it
  // would rewrite the API calls to an https:// origin that does not exist.
  if (apiOrigin.startsWith("https:")) policy.push(["upgrade-insecure-requests"]);

  return policy.map((directive) => directive.join(" ")).join("; ");
}
