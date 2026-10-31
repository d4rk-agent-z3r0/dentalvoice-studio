// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
"use client";

import { useRouter, useSearchParams } from "next/navigation";

import { RequireSession } from "@/components/auth/RequireSession";
import { ConversationsList } from "@/features/conversations/ConversationsList";
import { isConversationState } from "@/lib/api/types";

/** Keeps the state filter in the URL so a filtered list can be linked and survives reloads. */
export function ConversationsRoute() {
  const router = useRouter();
  const raw = useSearchParams().get("state");
  const state = raw !== null && isConversationState(raw) ? raw : null;
  return (
    <RequireSession>
      <ConversationsList
        state={state}
        onStateChange={(next) =>
          router.replace(next ? `/conversations?state=${next}` : "/conversations", {
            scroll: false,
          })
        }
      />
    </RequireSession>
  );
}
