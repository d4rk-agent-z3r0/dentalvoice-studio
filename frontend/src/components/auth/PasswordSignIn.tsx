// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
"use client";

import { useId, useRef, useState, type FormEvent } from "react";

import { ErrorMeta } from "@/components/ui/StateViews";
import { useApiClient } from "@/lib/api/ApiProvider";
import { toApiError, type ApiError } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth/AuthProvider";
import { profileFromTokenResponse } from "@/lib/auth/session-store";

import { useCountdown } from "./useCountdown";

/** What to show after a failed attempt: the message, and the server's code and request id. */
interface Failure {
  message: string;
  error: ApiError | null;
}

function seconds(count: number) {
  return count === 1 ? "1 second" : `${count} seconds`;
}

/**
 * Email and password sign-in against `POST /api/v1/auth/login`.
 *
 * The password field is uncontrolled: its value is read once on submit, sent in the request body
 * and cleared after every attempt. It never enters React state, storage, a URL or a log line.
 */
export function PasswordSignIn({ titleId }: { titleId: string }) {
  const api = useApiClient();
  const { signIn } = useAuth();
  const [email, setEmail] = useState("");
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [retryIn, startRetryCountdown] = useCountdown();
  const passwordRef = useRef<HTMLInputElement>(null);
  const emailId = useId();
  const passwordId = useId();
  const errorId = useId();
  const countdownId = useId();

  const blocked = pending || retryIn > 0;

  function clearPassword(focus: boolean) {
    const input = passwordRef.current;
    if (!input) return;
    input.value = "";
    if (focus) input.focus();
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (blocked) return;
    const password = passwordRef.current?.value ?? "";
    const trimmedEmail = email.trim();
    if (!trimmedEmail || !password) {
      setFailure({ message: "Enter your email and password.", error: null });
      clearPassword(false);
      return;
    }

    setPending(true);
    setFailure(null);
    let failed: Failure | null = null;
    try {
      const response = await api.login({ email: trimmedEmail, password });
      const result = signIn(response.access_token, "password", profileFromTokenResponse(response));
      if (!result.ok) failed = { message: result.message, error: null };
    } catch (caught) {
      const error = toApiError(caught);
      failed = { message: error.message, error };
    } finally {
      setPending(false);
    }
    // On success this form has already been replaced by the page; nothing below runs visibly.
    clearPassword(failed !== null);
    if (failed) {
      setFailure(failed);
      const wait = failed.error?.status === 429 ? failed.error.retryAfterSeconds : null;
      if (wait !== null) startRetryCountdown(wait);
    }
  }

  const describedBy = [failure ? errorId : null, retryIn > 0 ? countdownId : null]
    .filter(Boolean)
    .join(" ");

  return (
    <form
      method="post"
      aria-labelledby={titleId}
      onSubmit={onSubmit}
      className="mt-5 space-y-4"
      noValidate
    >
      <div className="space-y-1">
        <label htmlFor={emailId} className="block text-sm font-medium text-slate-800">
          Email
        </label>
        <input
          id={emailId}
          name="email"
          type="email"
          inputMode="email"
          autoComplete="username"
          autoCapitalize="none"
          spellCheck={false}
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          aria-invalid={failure ? true : undefined}
          aria-describedby={failure ? errorId : undefined}
          className="field-input"
        />
      </div>
      <div className="space-y-1">
        <label htmlFor={passwordId} className="block text-sm font-medium text-slate-800">
          Password
        </label>
        <input
          ref={passwordRef}
          id={passwordId}
          name="password"
          type="password"
          autoComplete="current-password"
          required
          aria-invalid={failure ? true : undefined}
          aria-describedby={failure ? errorId : undefined}
          className="field-input"
        />
      </div>

      {failure ? (
        <div
          id={errorId}
          role="alert"
          className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm"
        >
          <p className="text-rose-900">{failure.message}</p>
          {failure.error ? <ErrorMeta error={failure.error} /> : null}
        </div>
      ) : null}
      {retryIn > 0 ? (
        <p id={countdownId} className="text-sm font-medium text-slate-700">
          You can try again in {seconds(retryIn)}.
        </p>
      ) : null}

      <button
        type="submit"
        className="btn-primary w-full sm:w-auto"
        disabled={blocked}
        aria-describedby={describedBy || undefined}
      >
        {pending ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}
