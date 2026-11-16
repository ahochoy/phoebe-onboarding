/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const apiTarget = `http://localhost:${process.env.PHOEBE_PORT ?? 8080}`;

export default defineConfig({
  // Previews are served under a sub-path (e.g. PHOEBE_BASE=/pr-12/); /api stays at the origin root.
  base: process.env.PHOEBE_BASE ?? "/",
  plugins: [react(), tailwindcss()],
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
