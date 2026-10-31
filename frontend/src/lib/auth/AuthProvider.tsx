// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
"use client";

/**
 * Session state for the whole app. Pages only use `useAuth()` (status, display claims, sign out)
 * and `useApiClient()`; they never see how a token was obtained. The password form calls the
 * login endpoint and then `signIn(access_token, "password", profile)`; outside production a pasted
 * development token is accepted too. Switching clinic is another `signIn` with the new token.
 */
import { createContext, useContext, useMemo, useSyncExternalStore, type ReactNode } from "react";

import type { ApiError } from "@/lib/api/errors";

import {
  createSessionStore,
  type AuthMethod,
  type Session,
  type SessionProfile,
  type SessionStore,
  type SignedOutNotice,
} from "./session-store";
import { readDisplayClaims } from "./token";

export type SignInResult = { ok: true; session: Session } | { ok: false; message: string };

export interface AuthContextValue {
  status: "checking" | "signed_out" | "signed_in";
  session: Session | null;
  /** Why the previous session ended, when it did not end by the user's choice. */
  notice: SignedOutNotice | null;
  /** Starts (or replaces) the session. The profile is the server's view of user and clinics. */
  signIn(token: string, method: AuthMethod, profile?: SessionProfile | null): SignInResult;
  /** Attaches a profile fetched for `token`; ignored if the session has changed since. */
  setProfile(token: string, profile: SessionProfile): void;
  /** Discards the token. There is no server call: tokens are short-lived. */
  signOut(): void;
  /** Ends the session because the API rejected it (401). */
  rejectSession(error: ApiError): void;
  getToken(): string | null;
}

const AuthContext = createContext<AuthContextValue | null>(null);

let browserStore: SessionStore | null = null;
function defaultStore(): SessionStore {
  browserStore ??= createSessionStore();
  return browserStore;
}

export function AuthProvider({
  children,
  store: providedStore,
  now = Date.now,
}: {
  children: ReactNode;
  /** Injected in tests; the browser default mirrors the token to `sessionStorage`. */
  store?: SessionStore;
  now?: () => number;
}) {
  const store = providedStore ?? defaultStore();
  const snapshot = useSyncExternalStore(
    store.subscribe,
    store.getSnapshot,
    store.getServerSnapshot,
  );

  const value = useMemo<AuthContextValue>(
    () => ({
      status: snapshot.status,
      session: snapshot.status === "signed_in" ? snapshot.session : null,
      notice: snapshot.status === "signed_out" ? snapshot.notice : null,
      signIn(token, method, profile = null) {
        const trimmed = token.trim();
        const claims = readDisplayClaims(trimmed);
        const pasted = method === "developer_token";
        if (!claims) {
          return {
            ok: false,
            message: pasted
              ? "That does not look like an access token. Paste the full output of make dev-token."
              : "The server returned an access token this app cannot read.",
          };
        }
        if (claims.expiresAt !== null && claims.expiresAt <= now()) {
          return {
            ok: false,
            message: pasted
              ? "This token has expired. Run make dev-token for a new one."
              : "The server returned an access token that has already expired. Check the clock on this device.",
          };
        }
        return { ok: true, session: store.setSession(trimmed, method, profile) };
      },
      setProfile: store.setProfile,
      signOut() {
        store.clear({ kind: "signed_out", message: "You signed out." });
      },
      rejectSession(error) {
        store.clear({
          kind: "rejected",
          message: `The API rejected the session (${error.code}): ${error.message}`,
        });
      },
      getToken: store.getToken,
    }),
    [snapshot, store, now],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>.");
  return value;
}
