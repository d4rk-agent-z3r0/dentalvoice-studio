// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import { describe, expect, it } from "vitest";

import {
  SECURITY_HEADERS,
  apiConnectSources,
  buildContentSecurityPolicy,
  createNonce,
} from "./headers";

const NONCE = "bm9uY2UtZm9yLXRlc3Rz";

function directives(policy: string): Map<string, string[]> {
  return new Map(
    policy.split(";").map((part) => {
      const [name, ...sources] = part.trim().split(/\s+/);
      return [name, sources];
    }),
  );
}

describe("buildContentSecurityPolicy", () => {
  const production = buildContentSecurityPolicy({
    nonce: NONCE,
    apiBaseUrl: "http://localhost:8000",
    development: false,
  });

  it("builds the production policy", () => {
    expect(production).toBe(
      [
        "default-src 'self'",
        `script-src 'self' 'nonce-${NONCE}' 'strict-dynamic'`,
        `style-src 'self' 'nonce-${NONCE}'`,
        "img-src 'self'",
        "font-src 'self'",
        "connect-src 'self' http://localhost:8000 ws://localhost:8000",
        "media-src 'self' blob:",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
      ].join("; "),
    );
  });

  it("never allows eval or inline code in production", () => {
    expect(production).not.toContain("unsafe-eval");
    expect(production).not.toContain("unsafe-inline");
    expect(production).not.toMatch(/\*/);
  });

  it("adds only what the development server needs in development", () => {
    const dev = directives(
      buildContentSecurityPolicy({
        nonce: NONCE,
        apiBaseUrl: "http://localhost:8000",
        development: true,
      }),
    );
    expect(dev.get("script-src")).toEqual([
      "'self'",
      `'nonce-${NONCE}'`,
      "'strict-dynamic'",
      "'unsafe-eval'",
    ]);
    // The dev overlay injects styles without a nonce; a nonce would disable 'unsafe-inline'.
    expect(dev.get("style-src")).toEqual(["'self'", "'unsafe-inline'"]);
    expect(dev.get("connect-src")).toEqual(directives(production).get("connect-src"));
  });

  it("allows the API origin and its secure WebSocket counterpart, without the path", () => {
    const policy = directives(
      buildContentSecurityPolicy({
        nonce: NONCE,
        apiBaseUrl: "https://api.dentalvoice.example.org/v1/",
        development: false,
      }),
    );
    expect(policy.get("connect-src")).toEqual([
      "'self'",
      "https://api.dentalvoice.example.org",
      "wss://api.dentalvoice.example.org",
    ]);
    expect(policy.get("upgrade-insecure-requests")).toEqual([]);
  });

  it("only upgrades insecure requests when the API itself is HTTPS", () => {
    expect(directives(production).has("upgrade-insecure-requests")).toBe(false);
  });

  it("keeps the simulator's blob: clips playable and refuses framing", () => {
    const policy = directives(production);
    expect(policy.get("media-src")).toEqual(["'self'", "blob:"]);
    expect(policy.get("frame-ancestors")).toEqual(["'none'"]);
    expect(policy.get("default-src")).toEqual(["'self'"]);
  });

  it("refuses a nonce that could break out of the header", () => {
    for (const nonce of ["", "abc'; script-src *", "a b", "abc;"]) {
      expect(() =>
        buildContentSecurityPolicy({ nonce, apiBaseUrl: "http://localhost:8000", development: false }),
      ).toThrow(/nonce/);
    }
  });
});

describe("apiConnectSources", () => {
  it("maps http to ws and https to wss, keeping a non-default port", () => {
    expect(apiConnectSources("http://localhost:8011")).toEqual([
      "http://localhost:8011",
      "ws://localhost:8011",
    ]);
    expect(apiConnectSources("https://api.example.net:8443/base")).toEqual([
      "https://api.example.net:8443",
      "wss://api.example.net:8443",
    ]);
  });

  it("rejects a base URL that is not http(s)", () => {
    expect(() => apiConnectSources("ftp://files.example.com")).toThrow(/NEXT_PUBLIC_API_BASE_URL/);
    expect(() => apiConnectSources("not a url")).toThrow(/NEXT_PUBLIC_API_BASE_URL/);
  });
});

describe("createNonce", () => {
  it("returns 128 random bits, base64-encoded, different every time", () => {
    const values = new Set(Array.from({ length: 50 }, createNonce));
    expect(values.size).toBe(50);
    for (const value of values) {
      expect(value).toMatch(/^[A-Za-z0-9+/]{22}==$/);
    }
  });
});

describe("SECURITY_HEADERS", () => {
  it("sends the fixed browser security headers", () => {
    expect(Object.fromEntries(SECURITY_HEADERS.map(({ key, value }) => [key, value]))).toEqual({
      "X-Content-Type-Options": "nosniff",
      "Referrer-Policy": "no-referrer",
      "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
      "X-Frame-Options": "DENY",
    });
  });
});
