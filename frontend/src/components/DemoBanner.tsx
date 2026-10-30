// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
export const DEMO_NOTICE = "DEMO ENVIRONMENT — ALL PATIENTS AND CONVERSATIONS ARE SYNTHETIC.";

/** Persistent, non-dismissable notice required on every page. */
export function DemoBanner() {
  return (
    <div
      role="note"
      aria-label="Synthetic data notice"
      className="sticky top-0 z-50 w-full bg-amber-300 px-4 py-2 text-center text-xs font-semibold tracking-wide text-amber-950"
    >
      {DEMO_NOTICE}
    </div>
  );
}
