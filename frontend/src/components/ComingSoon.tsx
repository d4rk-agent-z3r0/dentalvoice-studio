// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import { PageHeader } from "@/components/ui/PageHeader";
import { EmptyState } from "@/components/ui/StateViews";

/** Placeholder for a section whose API does not exist yet. Shows no data, real or invented. */
export function ComingSoon({
  title,
  description,
  dependsOn,
}: {
  title: string;
  description: string;
  dependsOn: string;
}) {
  return (
    <>
      <PageHeader title={title} description={description} />
      <EmptyState title="Coming in a later milestone">
        <p>{dependsOn}</p>
        <p className="mt-2">Nothing is shown here until the backend provides it.</p>
      </EmptyState>
    </>
  );
}
