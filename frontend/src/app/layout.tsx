// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
import type { Metadata } from "next";
import "./globals.css";
import { DemoBanner } from "@/components/DemoBanner";
import { AppHeader } from "@/components/shell/AppHeader";
import { Providers } from "@/components/shell/Providers";

export const metadata: Metadata = {
  title: { default: "DentalVoice Studio", template: "%s · DentalVoice Studio" },
  description:
    "AI voice patient onboarding simulator for fictional dental clinics. All data is synthetic.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
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
