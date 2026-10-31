// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Whole seconds left until a deadline, ticking once a second. Each tick moves down by at least one
 * second and catches up with the clock when timers were throttled (a background tab), so it never
 * stalls and never runs longer than the server asked.
 */
export function useCountdown(): [remaining: number, start: (seconds: number) => void] {
  const [remaining, setRemaining] = useState(0);
  const deadline = useRef(0);

  useEffect(() => {
    if (remaining <= 0) return;
    const timer = setTimeout(() => {
      const byClock = Math.ceil((deadline.current - Date.now()) / 1000);
      setRemaining(Math.max(0, Math.min(remaining - 1, byClock)));
    }, 1000);
    return () => clearTimeout(timer);
  }, [remaining]);

  const start = useCallback((seconds: number) => {
    const whole = Math.max(0, Math.ceil(seconds));
    deadline.current = Date.now() + whole * 1000;
    setRemaining(whole);
  }, []);

  return [remaining, start];
}
