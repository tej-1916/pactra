import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  test: {
    globals: true,
    environment: "jsdom",
    // A real origin rather than about:blank, so relative fetches to the
    // /api/pactra/* proxy routes resolve the way they do in the browser.
    // (Storage itself is polyfilled in vitest.setup.ts — see the note there.)
    environmentOptions: { jsdom: { url: "http://localhost:3000" } },
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
});
