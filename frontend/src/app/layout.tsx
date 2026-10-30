import type { Metadata } from "next";
import "./globals.css";
import { DemoBanner } from "@/components/DemoBanner";

export const metadata: Metadata = {
  title: "DentalVoice Studio",
  description:
    "AI voice patient onboarding simulator for fictional dental clinics. All data is synthetic.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="flex min-h-full flex-col bg-slate-50 text-slate-900">
        <DemoBanner />
        {children}
      </body>
    </html>
  );
}
