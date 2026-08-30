import type { Metadata, Viewport } from "next";
import { IBM_Plex_Mono, Inter, Space_Grotesk } from "next/font/google";

import { Providers } from "./providers";
import { Sidebar } from "@/components/shell/Sidebar";
import { THEME_BOOTSTRAP_SCRIPT } from "@/lib/theme";
import "./globals.css";

/**
 * Three faces, three jobs, and the split is load-bearing rather than stylistic.
 *
 *   Space Grotesk  headings and the wordmark.
 *   Inter          everything read as prose.
 *   IBM Plex Mono  every MACHINE value — digests, reason codes, amounts, IDs.
 *
 * The mono face is the one that matters here: a transaction digest set in a
 * proportional font is a digest a reader cannot compare against another one,
 * and a merchant string set in the same face as an authoritative amount is
 * exactly the confusion `TaintedText` exists to prevent.
 */
const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });
const spaceGrotesk = Space_Grotesk({
  subsets: ["latin"],
  variable: "--font-space-grotesk",
  display: "swap",
});
const ibmPlexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-ibm-plex-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "PACTRA — Adversarial Transaction Security",
    template: "%s · PACTRA",
  },
  description:
    "Adversarial Transaction Security for Agentic Commerce. AI may propose and select; PACTRA controls authority and payments.",
};

export const viewport: Viewport = {
  // Both, in light-first order: the console ships a light default and a dark
  // inverse, and the browser chrome should follow whichever one is applied.
  //
  // These two literals are the ONLY colours outside `globals.css`, because a
  // meta tag cannot read a CSS custom property. They must stay equal to
  // `--pactra-ground` in each palette; nothing enforces that but this comment.
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f4f6fa" },
    { media: "(prefers-color-scheme: dark)", color: "#06080c" },
  ],
  colorScheme: "light dark",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      // The pre-paint script replaces this. It is stamped in the markup too so
      // that a browser with scripting disabled still gets the documented
      // default rather than an unthemed document.
      data-theme="light"
      className={`${inter.variable} ${spaceGrotesk.variable} ${ibmPlexMono.variable}`}
      suppressHydrationWarning
    >
      <head>
        {/* Inline and blocking on purpose: it must settle the palette before
            first paint. See lib/theme.ts. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP_SCRIPT }} />
      </head>
      <body className="min-h-dvh antialiased">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-60 focus:rounded focus:bg-[color:var(--color-surface-3)] focus:px-3 focus:py-2 focus:text-[12px] focus:text-[color:var(--color-ink)]"
        >
          Skip to content
        </a>
        <Providers>
          <Sidebar />
          <main id="main" className="min-h-dvh lg:pl-[248px]">
            <div className="mx-auto w-full max-w-[1560px] px-4 pt-16 pb-16 sm:px-6 lg:pt-8">
              {children}
            </div>
          </main>
        </Providers>
      </body>
    </html>
  );
}
