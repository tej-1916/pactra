import type { NextConfig } from "next";

/**
 * PACTRA console.
 *
 * `PACTRA_API_URL` and `PACTRA_REPORTS_DIR` are deliberately NOT exposed to the
 * browser. Every backend call is proxied through a Route Handler under
 * `/api/pactra/*`, so the API origin never appears in client bundles and no
 * credential can be introduced through a `NEXT_PUBLIC_` variable later without
 * that change being visible here.
 */
const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  outputFileTracingRoot: process.cwd(),
  // `next dev` otherwise writes AGENTS.md and CLAUDE.md into this workspace on
  // every start. They are generated tool output rather than authored guidance
  // for this project, and a file that reappears untracked after each dev run is
  // noise in every future diff. Turned off at the source rather than ignored.
  agentRules: false,
};

export default nextConfig;
