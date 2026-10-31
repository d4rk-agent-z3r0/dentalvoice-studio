// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
"use client";

import { Fragment, type ReactNode } from "react";

import { LoadingState } from "@/components/ui/StateViews";
import { useAuth } from "@/lib/auth/AuthProvider";

import { SignInScreen } from "./SignInScreen";

/**
 * Renders its children only with a session; otherwise the sign-in screen, in place.
 *
 * The children are keyed by the token's clinic, so switching clinic unmounts the whole page and
 * mounts it again: every in-flight request is aborted, every query refetches with the new token and
 * no state from the previous clinic (lists, selections, a running call) survives the switch.
 */
export function RequireSession({ children }: { children: ReactNode }) {
  const { status, session } = useAuth();
  if (status === "checking") return <LoadingState label="Checking your session…" />;
  if (!session) return <SignInScreen />;
  return <Fragment key={session.claims.clinicId ?? "no-clinic"}>{children}</Fragment>;
}
