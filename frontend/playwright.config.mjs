// Browser-Tests (Playwright): die ganze App wie ein Mensch bedienen.
//
// Startet zwei Server:
//   1. das Backend mit einer frischen SQLite-Datei und dem Mock-Tutor
//      (ANTHROPIC_API_KEY leer) – kostet nie echtes Geld;
//   2. die gebaute Oberflaeche (vite preview), die /api ans Backend weiterreicht.
// Aufruf:  cd frontend && npm run test:e2e
//
// E2E_PYTHON: welches Python das Backend startet (Standard python3).
// PLAYWRIGHT_CHROMIUM_PATH: fester Chromium-Pfad (z.B. in Cloud-Sitzungen).
import { defineConfig, devices } from "@playwright/test";

const python = process.env.E2E_PYTHON || "python3";
const chromium = process.env.PLAYWRIGHT_CHROMIUM_PATH;

export default defineConfig({
  testDir: "./e2e",
  testMatch: /.*\.spec\.mjs/,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false, // eine gemeinsame SQLite-Datei
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]] : "list",
  use: {
    baseURL: "http://localhost:4173",
    locale: "de-CH",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    ...devices["Desktop Chrome"],
    launchOptions: chromium ? { executablePath: chromium } : {},
  },
  webServer: [
    {
      command: `rm -f e2e.db && ${python} -m uvicorn app.main:app --port 8000`,
      cwd: "../backend",
      url: "http://localhost:8000/api/health",
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        DATABASE_URL: "sqlite:///./e2e.db",
        JWT_SECRET: "nur-fuer-browser-tests-kein-geheimnis-0123456789",
        ANTHROPIC_API_KEY: "",
        ABO_ENABLED: "true",
        REQUIRE_EMAIL_VERIFICATION: "false",
        MAGIC_LINK_DEV_RETURN: "true",
        FRONTEND_BASE_URL: "http://localhost:4173",
      },
    },
    {
      command: "npm run build && npx vite preview --port 4173 --strictPort",
      url: "http://localhost:4173",
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
