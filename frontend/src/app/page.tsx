// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import Link from "next/link";

const SECTIONS = [
  {
    href: "/simulator",
    title: "Simulator",
    body: "Run a synthetic voice caller scenario against the receptionist: hear both sides, watch the state, intake and measured latency.",
    available: true,
  },
  {
    href: "/conversations",
    title: "Conversations",
    body: "Review every call: transcript, state timeline, captured intake fields with their status, and the confirmed snapshot.",
    available: true,
  },
  {
    href: "/patients",
    title: "Patients",
    body: "Search patient records created from completed onboarding calls; open a profile for contact details, linked calls, confirmed intake and appointments.",
    available: true,
  },
  {
    href: "/appointments",
    title: "Appointments",
    body: "The clinic calendar in clinic-local time: look up open times, book for a patient, cancel or reschedule.",
    available: true,
  },
  {
    href: "/analytics",
    title: "Analytics",
    body: "Completion rates and measured latency, computed from persisted data only.",
    available: false,
  },
] as const;

export default function Home() {
  return (
    <div className="space-y-8">
      <section className="max-w-3xl">
        <h1 className="text-3xl font-bold tracking-tight text-slate-900">DentalVoice Studio</h1>
        <p className="mt-3 text-lg text-slate-700">
          An AI receptionist simulator for fictional dental clinics. Synthetic callers, a language
          model that proposes replies, and a deterministic onboarding workflow that decides what is
          recorded.
        </p>
      </section>
      <section aria-labelledby="sections-title">
        <h2 id="sections-title" className="sr-only">
          Sections
        </h2>
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {SECTIONS.map((section) => (
            <li key={section.href}>
              <Link
                href={section.href}
                className="card block h-full p-5 hover:border-teal-600 hover:shadow"
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="text-base font-semibold text-slate-900">{section.title}</span>
                  {section.available ? null : (
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">
                      Later milestone
                    </span>
                  )}
                </span>
                <span className="mt-2 block text-sm text-slate-600">{section.body}</span>
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
