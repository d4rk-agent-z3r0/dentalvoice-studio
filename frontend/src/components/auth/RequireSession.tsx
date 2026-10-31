// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
"use client";

import type { ReactNode } from "react";

import { LoadingState } from "@/components/ui/StateViews";
import { useAuth } from "@/lib/auth/AuthProvider";

import { DeveloperSignIn } from "./DeveloperSignIn";

/**
 * Renders its children only with a session; otherwise the sign-in screen, in place. Milestone 8
 * swaps `DeveloperSignIn` for the password form here and nowhere else.
 */
export function RequireSession({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  if (status === "checking") return <LoadingState label="Checking your session…" />;
  if (status === "signed_out") return <DeveloperSignIn />;
  return <>{children}</>;
}
