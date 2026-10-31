// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
"use client";

import { useId, useState, type FormEvent } from "react";

import { useAuth } from "@/lib/auth/AuthProvider";

/**
 * Development-only sign-in: paste a token printed by `make dev-token`. Rendered by `SignInScreen`
 * only when `NODE_ENV` is not `production`, below the password form.
 */
export function DeveloperSignIn() {
  const { signIn } = useAuth();
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
    <section aria-labelledby={`${inputId}-title`} className="mt-4 rounded-md bg-amber-50 p-4">
      <h3 id={`${inputId}-title`} className="text-base font-semibold text-slate-900">
        Developer sign-in
      </h3>
      <p className="mt-1 text-sm text-slate-700">
        Paste an access token issued for a seeded demo user. Not available in production builds.
      </p>

      <form onSubmit={onSubmit} className="mt-3 space-y-3" noValidate>
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
          <code className="rounded bg-white px-1 py-0.5 font-mono break-all text-slate-800">
            make dev-token EMAIL=demo.staff@example.com CLINIC=brightsmile
          </code>
          . The token is kept in this tab only and cleared when you sign out or close the tab.
        </p>
        {error ? (
          <p id={errorId} role="alert" className="text-sm font-medium text-rose-800">
            {error}
          </p>
        ) : null}
        <button type="submit" className="btn-secondary" disabled={token.trim().length === 0}>
          Sign in with token
        </button>
      </form>
    </section>
  );
}
