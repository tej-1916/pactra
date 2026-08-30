import type { Metadata, Viewport } from "next";

import { Sidebar } from "@/components/shell/Sidebar";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "PACTRA — Adversarial Transaction Security",
    template: "%s · PACTRA",
  },
  description:
    "Adversarial Transaction Security for Agentic Commerce. AI proposes; PACTRA decides what can move money.",
};

export const viewport: Viewport = {
  themeColor: "#06080c",
  colorScheme: "dark",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-dvh antialiased">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-60 focus:rounded focus:bg-[color:var(--color-surface-3)] focus:px-3 focus:py-2 focus:text-[12px] focus:text-[color:var(--color-ink)]"
        >
          Skip to content
        </a>
        <Sidebar />
        <main id="main" className="min-h-dvh lg:pl-[248px]">
          <div className="mx-auto w-full max-w-[1560px] px-4 pt-16 pb-16 sm:px-6 lg:pt-8">
            {children}
          </div>
        </main>
      </body>
    </html>
  );
}
