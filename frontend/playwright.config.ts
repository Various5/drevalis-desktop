import { defineConfig, devices } from '@playwright/test';

/**
 * Phase 0 smoke harness. Boots the Vite dev server (port 3000) and runs one
 * navigation check per top-level route. The backend is stubbed per-test
 * (see e2e/smoke.spec.ts), so the suite is self-contained and does not need
 * a live API on :8000. Specs live in ./e2e — outside the app tsconfig's
 * `include: ["src"]`, so they never enter the `build:strict` (tsc -b) graph.
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: 'http://localhost:3000',
    trace: 'on-first-retry',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:3000',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
