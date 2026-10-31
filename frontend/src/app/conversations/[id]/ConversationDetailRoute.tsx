// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
"use client";

import { use } from "react";

import { RequireSession } from "@/components/auth/RequireSession";
import { ConversationDetailView } from "@/features/conversations/ConversationDetailView";

export function ConversationDetailRoute({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return (
    <RequireSession>
      <ConversationDetailView key={id} conversationId={id} />
    </RequireSession>
  );
}
