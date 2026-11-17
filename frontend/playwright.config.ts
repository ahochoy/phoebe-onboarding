import { defineConfig, devices, type Project } from "@playwright/test";
import { PREVIEW_PORT as PORT } from "./e2e/preview";

const CI = !!process.env.CI;

// The built app is served by `vite preview`; its /api proxy points at the stack on PHOEBE_PORT.

// Each test carries one tag that says where it runs; a test runs only where it can
// fail differently. @all: every project. @desktop: the three desktop engines (keyboard).
// @mobile: both phones (bottom tabs, sheets). @journey: one desktop and one phone.
// @axe: one desktop and one phone (axe rules do not depend on the engine).
// @once: chromium only.
const browsers = [
  {
    name: "chromium",
    use: { ...devices["Desktop Chrome"] },
    grep: /@(all|desktop|journey|axe|once)\b/,
  },
  { name: "firefox", use: { ...devices["Desktop Firefox"] }, grep: /@(all|desktop)\b/ },
  { name: "webkit", use: { ...devices["Desktop Safari"] }, grep: /@(all|desktop)\b/ },
  { name: "mobile-safari", use: { ...devices["iPhone 15"] }, grep: /@(all|mobile|journey)\b/ },
  { name: "mobile-chrome", use: { ...devices["Pixel 8"] }, grep: /@(all|mobile|axe)\b/ },
] satisfies Project[];

const LIMITS = /limits\.spec\.ts$/;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: CI,
  // A shared CI runner also hosts Postgres, the API and vite preview; a browser process
  // can crash under that load. Retries keep one crash from failing the run, and the
  // report still marks the test flaky.
  retries: CI ? 2 : 0,
  // The API verifies at most four passwords at once (scrypt slots); one login per worker
  // at a time keeps every login inside that. Never raise this above 4. CI uses 2 to
  // leave CPU for the stack.
  workers: CI ? 2 : 4,
  // Reopens the kill switch before any test, in case an interrupted run left it shut.
  globalSetup: "./e2e/global-setup.ts",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: CI ? "on-first-retry" : "retain-on-failure",
    // The app honours reduced motion: no confetti, instant scrolls, no pulsing loaders.
    // Fewer moving parts for viewport checks and axe, and less CPU on the runner.
    reducedMotion: "reduce",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: `npx vite preview --port ${PORT} --strictPort`,
    url: `http://localhost:${PORT}`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
  projects: [
    ...browsers.map((b) => ({ ...b, testIgnore: LIMITS })),
    // The kill switch is global to the stack, so limits.spec.ts must never overlap with
    // any other test: it runs alone, once, after every browser's suite.
    {
      name: "limits",
      use: { ...devices["Desktop Chrome"] },
      testMatch: LIMITS,
      workers: 1,
      dependencies: browsers.map((b) => b.name),
    },
  ],
});
