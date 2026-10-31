// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
"use client";

import { useAuth } from "./AuthProvider";

/**
 * Whether to offer write actions (book, cancel, reschedule). Read from the token's claims for
 * display only: the backend checks the role on every request, so a hidden button is a courtesy
 * and a `403` is still handled wherever a write is sent.
 */
export function useCanWrite(): boolean {
  const { session } = useAuth();
  const role = session?.claims.role;
  return role === "admin" || role === "staff";
}
