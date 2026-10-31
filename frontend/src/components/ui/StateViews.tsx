// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import type { ReactNode } from "react";

import type { ApiError } from "@/lib/api/errors";

export function LoadingState({ label }: { label: string }) {
  return (
    <div
      role="status"
      className="flex items-center gap-3 rounded-lg border border-slate-200 bg-white px-4 py-6 text-sm text-slate-600"
    >
      <span
        aria-hidden="true"
        className="size-4 animate-spin rounded-full border-2 border-slate-300 border-t-teal-700 motion-reduce:animate-none"
      />
      {label}
    </div>
  );
}

export function EmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 bg-white px-6 py-10 text-center">
      <p className="text-base font-semibold text-slate-900">{title}</p>
      {children ? <div className="mx-auto mt-2 max-w-prose text-sm text-slate-600">{children}</div> : null}
      {action ? <div className="mt-4 flex justify-center">{action}</div> : null}
    </div>
  );
}

/** Shows the server's code, message and request id verbatim, so failures are traceable. */
export function ErrorState({
  title,
  error,
  onRetry,
}: {
  title: string;
  error: ApiError;
  onRetry?: () => void;
}) {
  return (
    <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-4 text-sm">
      <p className="font-semibold text-rose-900">{title}</p>
      <p className="mt-1 text-rose-900">{error.message}</p>
      <ErrorMeta error={error} />
      {onRetry ? (
        <button type="button" onClick={onRetry} className="btn-secondary mt-3">
          Try again
        </button>
      ) : null}
    </div>
  );
}

export function ErrorMeta({ error }: { error: ApiError }) {
  return (
    <p className="mt-1 font-mono text-xs text-rose-800">
      {error.code}
      {error.status > 0 ? ` · HTTP ${error.status}` : ""}
      {error.requestId ? ` · request ${error.requestId}` : ""}
    </p>
  );
}
