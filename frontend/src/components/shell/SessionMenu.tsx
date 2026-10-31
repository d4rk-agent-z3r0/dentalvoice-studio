// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useEffectEvent, useId, useRef, useState, type KeyboardEvent } from "react";

import { ErrorMeta } from "@/components/ui/StateViews";
import { useApiClient } from "@/lib/api/ApiProvider";
import { toApiError, type ApiError } from "@/lib/api/errors";
import type { ClinicMembership } from "@/lib/api/types";
import { useAuth } from "@/lib/auth/AuthProvider";
import { profileFromTokenResponse, type Session } from "@/lib/auth/session-store";
import { shortId } from "@/lib/format";

/** The list page above a detail page (`/patients/<id>` → `/patients`), or `null` on a list page. */
export function sectionListFor(pathname: string | null): string | null {
  const match = pathname?.match(/^(\/[^/]+)\/.+/);
  return match ? match[1] : null;
}

/**
 * After a reload only the token is restored (the profile is never stored), so the user and their
 * clinics are fetched again. A `401` ends the session through the API client; any other failure
 * leaves the header on the token's claims.
 */
function useProfileRestore(session: Session | null) {
  const api = useApiClient();
  const { setProfile } = useAuth();
  const token = session && session.profile === null ? session.token : null;
  const load = useEffectEvent((forToken: string, signal: AbortSignal) => {
    api.me({ signal }).then(
      (profile) => setProfile(forToken, profile),
      () => undefined,
    );
  });
  useEffect(() => {
    if (!token) return;
    const controller = new AbortController();
    load(token, controller.signal);
    return () => controller.abort();
  }, [token]);
}

function ClinicSwitcher({ session, clinics }: { session: Session; clinics: ClinicMembership[] }) {
  const api = useApiClient();
  const { signIn, getToken } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const panelId = useId();
  const titleId = useId();
  const currentId = session.profile?.clinic.id ?? session.claims.clinicId;

  function close() {
    setOpen(false);
    setError(null);
    toggleRef.current?.focus();
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape" && open) {
      event.stopPropagation();
      close();
    }
  }

  async function switchTo(clinic: ClinicMembership) {
    const tokenAtStart = session.token;
    setPendingId(clinic.id);
    setError(null);
    try {
      const response = await api.switchClinic(clinic.id);
      // Signed out, or switched elsewhere, while this request was in flight: drop the answer.
      if (getToken() !== tokenAtStart) return;
      const result = signIn(
        response.access_token,
        session.method,
        profileFromTokenResponse(response),
      );
      if (!result.ok) {
        setError(toApiError(new Error(result.message)));
        return;
      }
      setOpen(false);
      // A detail page belongs to the previous clinic: go to the list of the same section.
      const list = sectionListFor(pathname);
      if (list) router.replace(list);
    } catch (caught) {
      const failure = toApiError(caught);
      // A 401 has already ended the session (and unmounted this menu).
      if (!failure.isUnauthorized) setError(failure);
    } finally {
      setPendingId(null);
    }
  }

  return (
    <div className="relative" onKeyDown={onKeyDown}>
      <button
        ref={toggleRef}
        type="button"
        className="btn-secondary px-2 py-1 text-xs"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => (open ? close() : setOpen(true))}
      >
        Switch clinic
      </button>
      {open ? (
        <section
          id={panelId}
          aria-labelledby={titleId}
          className="card absolute right-0 z-30 mt-2 w-72 max-w-[calc(100vw-2rem)] p-3 text-sm"
        >
          <h2 id={titleId} className="text-sm font-semibold text-slate-900">
            Switch clinic
          </h2>
          <p className="mt-1 text-xs text-slate-600">
            Pages reload with the chosen clinic&apos;s data.
          </p>
          <ul className="mt-2 space-y-1">
            {clinics.map((clinic) => {
              const current = clinic.id === currentId;
              return (
                <li key={clinic.id}>
                  {current ? (
                    <p
                      aria-current="true"
                      className="flex items-center justify-between gap-2 rounded-md bg-teal-50 px-2 py-1.5 text-teal-900 ring-1 ring-teal-200"
                    >
                      <span className="font-medium">{clinic.name}</span>
                      <span className="text-xs">{clinic.role} · current</span>
                    </p>
                  ) : (
                    <button
                      type="button"
                      disabled={pendingId !== null}
                      onClick={() => void switchTo(clinic)}
                      className="flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-slate-800 hover:bg-slate-100 disabled:cursor-wait disabled:text-slate-400"
                    >
                      <span className="font-medium">{clinic.name}</span>
                      <span className="text-xs text-slate-600">
                        {pendingId === clinic.id ? "Switching…" : clinic.role}
                      </span>
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
          {error ? (
            <div role="alert" className="mt-2 rounded-md bg-rose-50 px-2 py-1.5 text-xs text-rose-900">
              <p>{error.message}</p>
              <ErrorMeta error={error} />
            </div>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}

/** The header's session area: who is signed in, where, as what; clinic switcher; sign out. */
export function SessionMenu() {
  const { status, session, signOut } = useAuth();
  useProfileRestore(session);

  if (status === "checking") return <p className="text-xs text-slate-500">Checking session…</p>;
  if (!session) return <p className="text-xs text-slate-600">Not signed in</p>;

  const profile = session.profile;
  const clinicId = profile?.clinic.id ?? session.claims.clinicId;
  const role = profile?.role ?? session.claims.role;

  return (
    <div className="flex flex-wrap items-center justify-end gap-x-3 gap-y-2 text-xs">
      <dl className="flex flex-wrap items-center gap-x-3 gap-y-1 text-slate-700">
        {profile ? (
          <div className="flex gap-1">
            <dt className="sr-only">Signed in as</dt>
            <dd className="font-semibold text-slate-900" title={profile.user.email}>
              {profile.user.display_name}
            </dd>
          </div>
        ) : null}
        <div className="flex gap-1">
          <dt className="text-slate-500">Clinic</dt>
          {profile ? (
            <dd className="font-medium" title={profile.clinic.timezone}>
              {profile.clinic.name}
            </dd>
          ) : (
            <dd className="font-mono" title={clinicId ?? undefined}>
              {clinicId ? shortId(clinicId) : "unknown"}
            </dd>
          )}
        </div>
        <div className="flex gap-1">
          <dt className="text-slate-500">Role</dt>
          <dd className="font-medium">{role ?? "unknown"}</dd>
        </div>
      </dl>
      {session.method === "developer_token" ? (
        <span className="rounded bg-amber-100 px-1.5 py-0.5 font-semibold text-amber-900">
          Dev token
        </span>
      ) : null}
      {profile && profile.clinics.length > 1 ? (
        <ClinicSwitcher session={session} clinics={profile.clinics} />
      ) : null}
      <button type="button" onClick={signOut} className="btn-secondary px-2 py-1 text-xs">
        Sign out
      </button>
    </div>
  );
}
