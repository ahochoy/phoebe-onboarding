import { defineConfig, devices, type Project } from "@playwright/test";
import { PREVIEW_PORT as PORT } from "./e2e/preview";

// The built app is served by `vite preview`; its /api proxy points at the stack on PHOEBE_PORT.

const browsers = [
  { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  { name: "firefox", use: { ...devices["Desktop Firefox"] } },
  { name: "webkit", use: { ...devices["Desktop Safari"] } },
  { name: "mobile-safari", use: { ...devices["iPhone 15"] } },
  { name: "mobile-chrome", use: { ...devices["Pixel 8"] } },
] satisfies Project[];

const LIMITS = /limits\.spec\.ts$/;
const MOBILE_ONLY = /mobile\.spec\.ts$/;

// The kill switch is global to the stack, so limits.spec.ts must never overlap with any
// other test. Every browser's ordinary suite runs first (in parallel); then each
// browser's limits run, one browser after the other.
const limitsProjects: Project[] = browsers.map((b, i) => ({
  ...b,
  name: `${b.name}-limits`,
  testMatch: LIMITS,
  workers: 1,
  dependencies: i === 0 ? browsers.map((x) => x.name) : [`${browsers[i - 1]!.name}-limits`],
}));

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  // The API verifies at most four passwords at once (scrypt slots); one login per worker
  // at a time keeps every login inside that.
  workers: 4,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: `npx vite preview --port ${PORT} --strictPort`,
    url: `http://localhost:${PORT}`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
  projects: [
    ...browsers.map((b) => ({
      ...b,
      testIgnore: b.use.isMobile ? [LIMITS] : [LIMITS, MOBILE_ONLY],
    })),
    ...limitsProjects,
  ],
});
