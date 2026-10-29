import fs from "node:fs";

import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests: a real browser, the real Next.js app, the real FastAPI backend, the real
 * Keycloak and PostgreSQL (Docker). Nothing is mocked.
 *
 * Needs: `docker compose up -d` in infrastructure/, and E2E_USER_PASSWORD in .env.local.
 * Starts the backend and the web app automatically if they aren't running yet.
 */
if (fs.existsSync(".env.local")) process.loadEnvFile(".env.local");

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1, // tests share the local Keycloak and database
  retries: 0,
  // A journey signs several people in; late in a full run the dev server is slow, so the whole
  // test gets more time than any single step (each step's wait is the expect timeout below).
  timeout: 120_000,
  // The web app runs in dev mode here, which compiles a page the first time it is visited; under
  // full-suite load that can take longer than Playwright's default 5 s wait for an element.
  expect: { timeout: 15_000 },
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        launchOptions: {
          args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"],
        },
      },
    },
  ],
  webServer: [
    {
      command:
        "..\\backend\\.venv\\Scripts\\python.exe -m uvicorn app.main:create_app --factory --port 8000",
      cwd: "../backend",
      url: "http://127.0.0.1:8000/api/v1/health",
      reuseExistingServer: true,
      timeout: 60_000,
    },
    {
      command: "npm run dev",
      url: "http://localhost:3000/login",
      reuseExistingServer: true,
      timeout: 120_000,
    },
  ],
});
