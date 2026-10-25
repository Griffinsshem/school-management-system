import { defineConfig, devices } from "@playwright/test";

// Read-only smoke checks against the deployed STAGING site (fake data only).
// Nothing is created or changed, so they can be run again at any time. Run
// from frontend/, with the demo accounts' password typed at a hidden prompt:
//
//   read -rsp "Demo password: " STAGING_PASSWORD; echo; export STAGING_PASSWORD
//   STAGING_URL=https://example.vercel.app npx playwright test -c playwright.staging.config.ts
//   unset STAGING_PASSWORD
//
// The normal browser tests (playwright.config.ts, folder e2e/) never touch
// staging, and these never start local servers.
const STAGING_URL = process.env.STAGING_URL ?? "";
if (!/^https:\/\/[^/]+$/.test(STAGING_URL)) {
  throw new Error("Set STAGING_URL to the staging site, like https://example.vercel.app");
}
if (!process.env.STAGING_PASSWORD) {
  throw new Error("Set STAGING_PASSWORD (the demo accounts' password) first.");
}

export default defineConfig({
  testDir: "./e2e-staging",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  // The free API sleeps when idle and takes about a minute to wake up.
  timeout: 120_000,
  expect: { timeout: 30_000 },
  reporter: "list",
  use: {
    baseURL: STAGING_URL,
    // No traces, screenshots or videos: they would record the typed password.
    trace: "off",
    screenshot: "off",
    video: "off",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
