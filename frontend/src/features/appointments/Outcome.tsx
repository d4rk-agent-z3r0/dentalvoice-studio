// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import type { ReactNode } from "react";

import { ErrorMeta } from "@/components/ui/StateViews";
import type { ApiError } from "@/lib/api/errors";

export type Outcome =
  | { kind: "success"; message: ReactNode }
  | { kind: "error"; title: string; error: ApiError };

/** The result of a write, exactly as the server reported it. */
export function OutcomeMessage({ outcome }: { outcome: Outcome | null }) {
  if (!outcome) return null;
  if (outcome.kind === "success") {
    return (
      <div
        role="status"
        className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-900"
      >
        {outcome.message}
      </div>
    );
  }
  return (
    <div role="alert" className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm">
      <p className="font-semibold text-rose-900">{outcome.title}</p>
      <p className="mt-1 text-rose-900">{outcome.error.message}</p>
      <ErrorMeta error={outcome.error} />
    </div>
  );
}
