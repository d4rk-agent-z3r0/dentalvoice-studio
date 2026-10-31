// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
/**
 * The access token lives in memory and is mirrored to `sessionStorage` (per tab, cleared when the
 * tab closes) so a reload keeps the session. Storage can be unavailable (private mode, blocked site
 * data), so every access is guarded and the app keeps working from memory alone.
 *
 * Exposed as an external store for `useSyncExternalStore`: the server snapshot is always
 * `checking`, so prerendered HTML never depends on browser storage and hydration cannot mismatch.
 */
import type { AuthMe, AuthTokenResponse } from "@/lib/api/types";

import { readDisplayClaims, type DisplayClaims } from "./token";

/** How the session started: the login endpoint, or a pasted development token. */
export type AuthMethod = "password" | "developer_token";

const AUTH_METHODS: readonly AuthMethod[] = ["password", "developer_token"];

function isAuthMethod(value: unknown): value is AuthMethod {
  return AUTH_METHODS.includes(value as AuthMethod);
}

/**
 * Who the session is for, as the server reported it (login, switch-clinic or `GET /auth/me`).
 * Display only, like the claims. Kept in memory and never written to storage, so a reload fetches
 * it again with `me`.
 */
export type SessionProfile = AuthMe;

/** The profile part of a login or switch-clinic response (everything but the token). */
export function profileFromTokenResponse(response: AuthTokenResponse): SessionProfile {
  return {
    user: response.user,
    clinic: response.clinic,
    role: response.role,
    clinics: response.clinics,
  };
}

export interface Session {
  token: string;
  method: AuthMethod;
  claims: DisplayClaims;
  profile: SessionProfile | null;
}

export interface SignedOutNotice {
  kind: "signed_out" | "rejected";
  message: string;
}

export type AuthSnapshot =
  | { status: "checking" }
  | { status: "signed_out"; notice: SignedOutNotice | null }
  | { status: "signed_in"; session: Session };

export interface SessionStore {
  subscribe(listener: () => void): () => void;
  getSnapshot(): AuthSnapshot;
  getServerSnapshot(): AuthSnapshot;
  getToken(): string | null;
  setSession(token: string, method: AuthMethod, profile?: SessionProfile | null): Session;
  /** Attaches a profile, but only while `token` is still the current session's token. */
  setProfile(token: string, profile: SessionProfile): void;
  clear(notice?: SignedOutNotice | null): void;
}

export const SESSION_STORAGE_KEY = "dentalvoice.session.v1";

const CHECKING: AuthSnapshot = { status: "checking" };

function defaultStorage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    return null;
  }
}

function readPersisted(storage: Storage | null): Session | null {
  if (!storage) return null;
  try {
    const raw = storage.getItem(SESSION_STORAGE_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) return null;
    const { token, method } = parsed as Record<string, unknown>;
    if (typeof token !== "string" || !isAuthMethod(method)) return null;
    const claims = readDisplayClaims(token);
    return claims ? { token, method, claims, profile: null } : null;
  } catch {
    return null;
  }
}

export function createSessionStore(getStorage: () => Storage | null = defaultStorage): SessionStore {
  let snapshot: AuthSnapshot | null = null; // null until first read on the client
  const listeners = new Set<() => void>();

  function current(): AuthSnapshot {
    if (snapshot === null) {
      const restored = readPersisted(getStorage());
      snapshot = restored
        ? { status: "signed_in", session: restored }
        : { status: "signed_out", notice: null };
    }
    return snapshot;
  }

  function publish(next: AuthSnapshot) {
    snapshot = next;
    listeners.forEach((listener) => listener());
  }

  return {
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    getSnapshot: current,
    getServerSnapshot: () => CHECKING,
    getToken() {
      const value = current();
      return value.status === "signed_in" ? value.session.token : null;
    },
    setSession(token, method, profile = null) {
      const claims = readDisplayClaims(token);
      if (!claims) throw new Error("Not an access token.");
      const session: Session = { token, method, claims, profile };
      try {
        getStorage()?.setItem(SESSION_STORAGE_KEY, JSON.stringify({ token, method }));
      } catch {
        // Storage full or blocked: the session still works for this page view.
      }
      publish({ status: "signed_in", session });
      return session;
    },
    setProfile(token, profile) {
      const value = current();
      if (value.status !== "signed_in" || value.session.token !== token) return;
      publish({ status: "signed_in", session: { ...value.session, profile } });
    },
    clear(notice = null) {
      try {
        getStorage()?.removeItem(SESSION_STORAGE_KEY);
      } catch {
        // Nothing persisted, or storage blocked: memory is cleared below either way.
      }
      publish({ status: "signed_out", notice });
    },
  };
}
