// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
/**
 * Reads the claims of an access token **for display only**. The signature is not (and cannot be)
 * checked here: the backend verifies every request and is the only authority on clinic and role.
 */

export interface DisplayClaims {
  userId: string | null;
  clinicId: string | null;
  role: string | null;
  /** Expiry as epoch milliseconds, when the token carries `exp`. */
  expiresAt: number | null;
}

function base64UrlDecode(segment: string): string {
  const base64 = segment.replace(/-/g, "+").replace(/_/g, "/");
  const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), "=");
  const binary = atob(padded);
  const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}

const optionalString = (value: unknown) => (typeof value === "string" ? value : null);

/** Returns `null` when the value does not look like a JWT with a JSON payload. */
export function readDisplayClaims(token: string): DisplayClaims | null {
  const parts = token.split(".");
  if (parts.length !== 3 || parts.some((part) => part.length === 0)) return null;
  let payload: unknown;
  try {
    payload = JSON.parse(base64UrlDecode(parts[1]));
  } catch {
    return null;
  }
  if (typeof payload !== "object" || payload === null || Array.isArray(payload)) return null;
  const claims = payload as Record<string, unknown>;
  return {
    userId: optionalString(claims.sub),
    clinicId: optionalString(claims.clinic_id),
    role: optionalString(claims.role),
    expiresAt: typeof claims.exp === "number" ? claims.exp * 1000 : null,
  };
}
