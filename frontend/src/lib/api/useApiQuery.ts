// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
"use client";

import { useCallback, useEffect, useEffectEvent, useState } from "react";

import { toApiError, type ApiError } from "./errors";

export type QueryState<T> =
  | { status: "loading" }
  | { status: "error"; error: ApiError }
  | { status: "success"; data: T };

type Settled<T> = { requestKey: string } & (
  | { status: "error"; error: ApiError }
  | { status: "success"; data: T }
);

/**
 * Fetches data for a key and refetches when the key changes. The result is tagged with the key it
 * was fetched for, so a stale response is never shown as current: anything not settled for the
 * current key reads as `loading`. In-flight requests are aborted when the key changes or the
 * component unmounts.
 */
export function useApiQuery<T>(
  key: string,
  fetcher: (signal: AbortSignal) => Promise<T>,
): QueryState<T> & { reload: () => void } {
  const [attempt, setAttempt] = useState(0);
  const [settled, setSettled] = useState<Settled<T> | null>(null);
  const requestKey = `${key}#${attempt}`;
  const run = useEffectEvent((signal: AbortSignal) => fetcher(signal));

  useEffect(() => {
    const controller = new AbortController();
    run(controller.signal).then(
      (data) => {
        if (!controller.signal.aborted) setSettled({ requestKey, status: "success", data });
      },
      (error: unknown) => {
        if (!controller.signal.aborted) {
          setSettled({ requestKey, status: "error", error: toApiError(error) });
        }
      },
    );
    return () => controller.abort();
  }, [requestKey]);

  const reload = useCallback(() => setAttempt((value) => value + 1), []);

  if (settled === null || settled.requestKey !== requestKey) return { status: "loading", reload };
  if (settled.status === "error") return { status: "error", error: settled.error, reload };
  return { status: "success", data: settled.data, reload };
}
