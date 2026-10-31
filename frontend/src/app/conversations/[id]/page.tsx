// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingState } from "@/components/ui/StateViews";

import { ConversationDetailRoute } from "./ConversationDetailRoute";

export const metadata: Metadata = { title: "Conversation" };

/** The id is only known at request time, so it is read below a Suspense boundary. */
export default function ConversationPage({ params }: PageProps<"/conversations/[id]">) {
  return (
    <Suspense fallback={<LoadingState label="Loading conversation…" />}>
      <ConversationDetailRoute params={params} />
    </Suspense>
  );
}
