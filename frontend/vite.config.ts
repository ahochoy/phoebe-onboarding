/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

const apiTarget = `http://localhost:${process.env.PHOEBE_PORT ?? 8080}`;

// Adds og:image only when VITE_SITE_ORIGIN is set. ci/deploy.sh sets it for staging and production;
// PR previews build without it, so they omit the tag.
function ogImage(base: string): Plugin {
  return {
    name: "phoebe-og-image",
    transformIndexHtml() {
      const origin = process.env.VITE_SITE_ORIGIN?.replace(/\/+$/, "");
      if (!origin) return [];
      return [
        {
          tag: "meta",
          attrs: { property: "og:image", content: `${origin}${base}og/link-preview.jpg` },
          injectTo: "head",
        },
      ];
    },
  };
}

const base = process.env.PHOEBE_BASE ?? "/";

export default defineConfig({
  // Previews are served under a sub-path (e.g. PHOEBE_BASE=/pr-12/); /api stays at the origin root.
  base,
  plugins: [react(), tailwindcss(), ogImage(base)],
  // The About popover's version line. ci/deploy.sh sets PHOEBE_VERSION
  // ("v0.1.6 (eed737f)" in production, "main (<sha>)" on staging).
  define: { __APP_VERSION__: JSON.stringify(process.env.PHOEBE_VERSION || "dev") },
  server: { port: 5173, proxy: { "/api": apiTarget } },
  preview: { proxy: { "/api": apiTarget } },
  test: {
    environment: "jsdom",
    // e2e/ holds Playwright specs, which vitest must not pick up.
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["./src/test/setup.ts"],
    globals: false,
    css: false,
  },
});
