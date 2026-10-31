// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import type { Metadata } from "next";

import { ComingSoon } from "@/components/ComingSoon";

export const metadata: Metadata = { title: "Analytics" };

export default function AnalyticsPage() {
  return (
    <ComingSoon
      title="Analytics"
      description="Completion rates and measured stage latency, computed from persisted data only."
      dependsOn="The analytics API (GET /api/v1/analytics/summary and /latency) is not available yet."
    />
  );
}
