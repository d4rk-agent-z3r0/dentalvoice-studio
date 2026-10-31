// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
"use client";

import { useId, useState, type FormEvent } from "react";

import { useAuth } from "@/lib/auth/AuthProvider";

/**
 * Development-only sign-in: paste a token printed by `make dev-token`. Replaced by the password
 * login in Milestone 8; it only calls `signIn`, so nothing else changes when it is swapped.
 */
export function DeveloperSignIn() {
  const { signIn, notice } = useAuth();
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const inputId = useId();
  const helpId = useId();
  const errorId = useId();

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const result = signIn(token, "developer_token");
    if (result.ok) {
      setToken("");
      setError(null);
    } else {
      setError(result.message);
    }
  }

  return (
    <section aria-labelledby={`${inputId}-title`} className="card mx-auto w-full max-w-xl p-6">
      <p className="inline-flex rounded bg-amber-100 px-2 py-0.5 text-xs font-semibold tracking-wide text-amber-900 uppercase">
        Development only
      </p>
      <h2 id={`${inputId}-title`} className="mt-3 text-xl font-semibold text-slate-900">
        Developer sign-in
      </h2>
      <p className="mt-2 text-sm text-slate-600">
        Real login arrives in Milestone 8. Until then, paste an access token issued for a seeded
        demo user. The API checks the token on every request; the clinic and role shown in the header
        are read from it for display only.
      </p>

      {notice && notice.kind === "rejected" ? (
        <p role="alert" className="mt-4 rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-900">
          {notice.message}
        </p>
      ) : null}

      <form onSubmit={onSubmit} className="mt-5 space-y-3" noValidate>
        <label htmlFor={inputId} className="block text-sm font-medium text-slate-800">
          Access token
        </label>
        <textarea
          id={inputId}
          name="token"
          value={token}
          onChange={(event) => setToken(event.target.value)}
          rows={4}
          required
          spellCheck={false}
          autoComplete="off"
          aria-describedby={error ? `${helpId} ${errorId}` : helpId}
          aria-invalid={error ? true : undefined}
          className="field-input font-mono text-xs break-all"
        />
        <p id={helpId} className="text-xs text-slate-600">
          From the repository root run{" "}
          <code className="rounded bg-slate-100 px-1 py-0.5 font-mono text-slate-800">
            make dev-token EMAIL=demo.staff@example.com CLINIC=brightsmile
          </code>
          . The token is kept in this tab only and cleared when you sign out or close the tab.
        </p>
        {error ? (
          <p id={errorId} role="alert" className="text-sm font-medium text-rose-800">
            {error}
          </p>
        ) : null}
        <button type="submit" className="btn-primary" disabled={token.trim().length === 0}>
          Sign in with token
        </button>
      </form>
    </section>
  );
}
