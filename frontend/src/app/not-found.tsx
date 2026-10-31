// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import Link from "next/link";

import { EmptyState } from "@/components/ui/StateViews";

export default function NotFound() {
  return (
    <EmptyState
      title="Page not found"
      action={
        <Link href="/" className="btn-secondary">
          Back to the overview
        </Link>
      }
    >
      <p>There is no page at this address.</p>
    </EmptyState>
  );
}
