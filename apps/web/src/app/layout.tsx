import type { Metadata, Viewport } from "next";
import { IBM_Plex_Mono, Inter, Space_Grotesk } from "next/font/google";

import { Providers } from "./providers";
import { Navbar } from "@/components/shell/Navbar";
import { THEME_BOOTSTRAP_SCRIPT } from "@/lib/theme";
import "./globals.css";

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
    default: "PACTRA — Deterministic Transaction Verification for Agentic Commerce",
    template: "%s · PACTRA",
  },
  applicationName: "PACTRA",
  description:
    "Deterministic transaction verification, admission, canonical authorization, and payment execution controls for agentic commerce (ADMIT → BIND → EXECUTE).",
  openGraph: {
    title: "PACTRA — Deterministic Transaction Verification for Agentic Commerce",
    description:
      "Deterministic transaction verification, admission, canonical authorization, and payment execution controls for agentic commerce (ADMIT → BIND → EXECUTE).",
    siteName: "PACTRA",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "PACTRA — Deterministic Transaction Verification for Agentic Commerce",
    description:
      "Deterministic transaction verification, admission, canonical authorization, and payment execution controls for agentic commerce (ADMIT → BIND → EXECUTE).",
  },
};

export const viewport: Viewport = {
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
      className={`${inter.variable} ${spaceGrotesk.variable} ${ibmPlexMono.variable}`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP_SCRIPT }} />
      </head>
      <body className="min-h-dvh antialiased bg-[color:var(--pactra-ground)]">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-60 focus:rounded focus:bg-[color:var(--color-surface-3)] focus:px-3 focus:py-2 focus:text-[12px] focus:text-[color:var(--color-ink)]"
        >
          Skip to content
        </a>
        <Providers>
          <Navbar />
          <main id="main" className="min-h-[calc(100dvh-64px)] pb-16">
            {children}
          </main>
        </Providers>
      </body>
    </html>
  );
}
