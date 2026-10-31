// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
"use client";

import { useId, useState } from "react";

import { useAuth } from "@/lib/auth/AuthProvider";

import { DeveloperSignIn } from "./DeveloperSignIn";
import { PasswordSignIn } from "./PasswordSignIn";

/**
 * The sign-in screen shown in place of any page without a session: email and password first.
 * Outside production a pasted developer token is offered as a secondary option; the check is on
 * `NODE_ENV`, which Next.js inlines, so production bundles do not contain that path at all.
 */
export function SignInScreen() {
  const { notice } = useAuth();
  const [developerToken, setDeveloperToken] = useState(false);
  const titleId = useId();
  const developerPanelId = useId();
  const developerTokenAllowed = process.env.NODE_ENV !== "production";

  return (
    <section aria-labelledby={titleId} className="card mx-auto w-full max-w-md p-6">
      <h2 id={titleId} className="text-xl font-semibold text-slate-900">
        Sign in
      </h2>
      <p className="mt-2 text-sm text-slate-600">
        Use a seeded demo account. Every clinic, patient and call in DentalVoice Studio is
        synthetic.
      </p>

      {notice && notice.kind === "rejected" ? (
        <p role="alert" className="mt-4 rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-900">
          {notice.message}
        </p>
      ) : null}

      <PasswordSignIn titleId={titleId} />

      {developerTokenAllowed ? (
        <div className="mt-6 border-t border-slate-200 pt-4">
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              className="text-sm font-medium text-teal-800 underline underline-offset-2 hover:text-teal-900"
              aria-expanded={developerToken}
              aria-controls={developerPanelId}
              onClick={() => setDeveloperToken((open) => !open)}
            >
              {developerToken ? "Hide developer token sign-in" : "Use a developer token instead"}
            </button>
            <span className="rounded bg-amber-100 px-1.5 py-0.5 text-xs font-semibold text-amber-900">
              Development only
            </span>
          </div>
          <div id={developerPanelId} hidden={!developerToken}>
            {developerToken ? <DeveloperSignIn /> : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}
