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
};

export default nextConfig;
