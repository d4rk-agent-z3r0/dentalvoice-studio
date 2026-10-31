// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import type { Metadata } from "next";
import { Suspense } from "react";

import { PageHeader } from "@/components/ui/PageHeader";
import { LoadingState } from "@/components/ui/StateViews";

import { ConversationsRoute } from "./ConversationsRoute";

export const metadata: Metadata = { title: "Conversations" };

export default function ConversationsPage() {
  return (
    <>
      <PageHeader
        title="Conversations"
        description="Every simulated call for your clinic, newest first. Open one for its transcript, state timeline and captured intake."
      />
      <Suspense fallback={<LoadingState label="Loading conversations…" />}>
        <ConversationsRoute />
      </Suspense>
    </>
  );
}
