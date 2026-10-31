// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import type { Metadata } from "next";
import { connection } from "next/server";
import "./globals.css";
import { DemoBanner } from "@/components/DemoBanner";
import { AppHeader } from "@/components/shell/AppHeader";
import { Providers } from "@/components/shell/Providers";

export const metadata: Metadata = {
  title: { default: "DentalVoice Studio", template: "%s · DentalVoice Studio" },
  description:
    "AI voice patient onboarding simulator for fictional dental clinics. All data is synthetic.",
};

/**
 * Every page renders per request so that Next.js can put the proxy's CSP nonce on all of its
 * scripts: a prerendered (static or partial) shell is built before any request exists and cannot
 * carry a per-request nonce (see the Next.js CSP guide). Waiting for the connection here, outside
 * any `<Suspense>`, is a blocking root, which `instant = false` allows. Pages are client-rendered
 * behind the session check anyway, so nothing cacheable is lost.
 */
export const instant = false;

export default async function RootLayout({ children }: LayoutProps<"/">) {
  await connection();
  return (
    <html lang="en" className="h-full antialiased">
      <body className="flex min-h-full flex-col bg-slate-50 text-slate-900">
        <a
          href="#main"
          className="sr-only z-[60] rounded-md bg-white px-3 py-2 text-sm font-semibold text-teal-900 focus:not-sr-only focus:fixed focus:top-12 focus:left-4"
        >
          Skip to main content
        </a>
        <DemoBanner />
        <Providers>
          <AppHeader />
          <main id="main" tabIndex={-1} className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6">
            {children}
          </main>
        </Providers>
        <footer className="border-t border-slate-200 bg-white px-4 py-4 text-center text-xs text-slate-600">
          DentalVoice Studio is a portfolio demonstration. Clinics, patients and calls are fictional.
        </footer>
      </body>
    </html>
  );
}
