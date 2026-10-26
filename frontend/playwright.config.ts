import { defineConfig, devices } from "@playwright/test";

// Browser tests: a real Chromium drives the real frontend, which forwards
// /api to a real Flask API on the test database. Run from frontend/ with the
// backend's virtual environment active (the API is started with `python`):
//
//   npx playwright test
//
// Both servers are started here on their own ports (3100 and 5001), so they
// do not clash with `npm run dev` (3000) and `flask run` (5000).
const API_ORIGIN = "http://127.0.0.1:5001";
const WEB_ORIGIN = "http://127.0.0.1:3100";
// A fake secret for these tests only, so the frontend-to-API handshake is
// tested exactly as on the real hosts. Keep in sync with
// backend/scripts/e2e_server.py.
const PROXY_SHARED_SECRET = "e2e-only-proxy-secret-never-used-anywhere-else";

export default defineConfig({
  testDir: "./e2e",
  // The tests share one database, so they run one at a time.
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: !!process.env.CI,
  reporter: "list",
  use: {
    baseURL: WEB_ORIGIN,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      // Empties the *_test database, adds fake data and serves the API.
      command: "python ../backend/scripts/e2e_server.py",
      url: `${API_ORIGIN}/api/v1/health`,
      reuseExistingServer: false,
      timeout: 60_000,
      stdout: "ignore",
      stderr: "pipe",
    },
    {
      // A production build, so the tests check what will be deployed.
      command: "npm run build && npx next start --hostname 127.0.0.1 --port 3100",
      url: `${WEB_ORIGIN}/login`,
      // TRUST_X_FORWARDED_FOR: these tests act as the visitor's host, as
      // Vercel does (see src/proxy.ts).
      env: { API_ORIGIN, PROXY_SHARED_SECRET, TRUST_X_FORWARDED_FOR: "1" },
      reuseExistingServer: false,
      timeout: 180_000,
      stdout: "ignore",
      stderr: "pipe",
    },
  ],
});
