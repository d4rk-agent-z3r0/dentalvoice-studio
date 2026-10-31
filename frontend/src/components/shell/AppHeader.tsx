// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense } from "react";

import { useAuth } from "@/lib/auth/AuthProvider";
import { shortId } from "@/lib/format";

export const NAV_ITEMS = [
  { href: "/simulator", label: "Simulator" },
  { href: "/conversations", label: "Conversations" },
  { href: "/patients", label: "Patients" },
  { href: "/appointments", label: "Appointments" },
  { href: "/analytics", label: "Analytics" },
] as const;

function isActive(pathname: string | null, href: string) {
  return pathname === href || (pathname?.startsWith(`${href}/`) ?? false);
}

function NavLinks({ pathname }: { pathname: string | null }) {
  return (
    <ul className="flex flex-wrap gap-1 lg:flex-nowrap">
      {NAV_ITEMS.map((item) => {
        const active = isActive(pathname, item.href);
        return (
          <li key={item.href} className="shrink-0">
            <Link
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={`block rounded-md px-3 py-2 text-sm font-medium ${
                active
                  ? "bg-teal-50 text-teal-900 ring-1 ring-teal-200"
                  : "text-slate-700 hover:bg-slate-100 hover:text-slate-900"
              }`}
            >
              {item.label}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

function ActiveNavLinks() {
  return <NavLinks pathname={usePathname()} />;
}

function SessionSummary() {
  const { status, session, signOut } = useAuth();
  if (status === "checking") return <p className="text-xs text-slate-500">Checking session…</p>;
  if (!session) return <p className="text-xs text-slate-600">Not signed in</p>;
  const { clinicId, role } = session.claims;
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
      <dl className="flex flex-wrap items-center gap-x-3 gap-y-1 text-slate-700">
        <div className="flex gap-1">
          <dt className="text-slate-500">Clinic</dt>
          <dd className="font-mono" title={clinicId ?? undefined}>
            {clinicId ? shortId(clinicId) : "unknown"}
          </dd>
        </div>
        <div className="flex gap-1">
          <dt className="text-slate-500">Role</dt>
          <dd className="font-medium">{role ?? "unknown"}</dd>
        </div>
      </dl>
      <span className="rounded bg-amber-100 px-1.5 py-0.5 font-semibold text-amber-900">
        Dev token
      </span>
      <button type="button" onClick={signOut} className="btn-secondary px-2 py-1 text-xs">
        Sign out
      </button>
    </div>
  );
}

export function AppHeader() {
  return (
    <header className="border-b border-slate-200 bg-white">
      {/* DOM order is brand, nav, session; on narrow screens CSS moves the nav onto its own row. */}
      <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3 sm:px-6">
        <Link href="/" className="order-1 flex items-center gap-2 text-slate-900">
          <span
            aria-hidden="true"
            className="grid size-8 place-items-center rounded-md bg-teal-700 text-sm font-bold text-white"
          >
            DV
          </span>
          <span className="text-lg font-semibold tracking-tight">DentalVoice Studio</span>
        </Link>
        <nav aria-label="Primary" className="order-3 -mx-1 w-full lg:order-2 lg:mx-0 lg:w-auto">
          {/* The active link reads the URL, which is unknown while prerendering dynamic routes. */}
          <Suspense fallback={<NavLinks pathname={null} />}>
            <ActiveNavLinks />
          </Suspense>
        </nav>
        <div className="order-2 ml-auto lg:order-3">
          <SessionSummary />
        </div>
      </div>
    </header>
  );
}
