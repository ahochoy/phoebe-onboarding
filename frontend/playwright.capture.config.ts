import { defineConfig, devices } from "@playwright/test";

// Owner-run README capture (`make screenshots`). It drives a deployed environment, staging
// by default, with real Bedrock answers, so it is kept out of `make e2e` and CI: separate
// config, separate test dir. The password comes from the environment only.
export default defineConfig({
  testDir: "./capture",
  testMatch: /\.capture\.ts$/,
  workers: 1,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 30_000 },
  reporter: [["list"]],
  use: {
    baseURL: process.env.PHOEBE_CAPTURE_URL ?? "https://d3vws9k2ggm24m.cloudfront.net",
    reducedMotion: "reduce",
  },
  projects: [
    {
      name: "desktop",
      grep: /@desktop\b/,
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1280, height: 800 },
        deviceScaleFactor: 2,
      },
    },
    {
      name: "phone",
      grep: /@phone\b/,
      use: { ...devices["iPhone 15"], defaultBrowserType: "chromium" },
    },
  ],
});
