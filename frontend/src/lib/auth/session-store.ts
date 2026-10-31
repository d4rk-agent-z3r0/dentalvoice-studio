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
import { readDisplayClaims, type DisplayClaims } from "./token";

/** How the token was obtained. Milestone 8 adds `"password"` (login endpoint). */
export type AuthMethod = "developer_token";

export interface Session {
  token: string;
  method: AuthMethod;
  claims: DisplayClaims;
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
  setSession(token: string, method: AuthMethod): Session;
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
    if (typeof token !== "string" || method !== "developer_token") return null;
    const claims = readDisplayClaims(token);
    return claims ? { token, method, claims } : null;
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
    setSession(token, method) {
      const claims = readDisplayClaims(token);
      if (!claims) throw new Error("Not an access token.");
      const session: Session = { token, method, claims };
      try {
        getStorage()?.setItem(SESSION_STORAGE_KEY, JSON.stringify({ token, method }));
      } catch {
        // Storage full or blocked: the session still works for this page view.
      }
      publish({ status: "signed_in", session });
      return session;
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
