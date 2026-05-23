import { test, expect } from '@playwright/test';

/**
 * Per-route smoke test. For each top-level route: navigate, assert we landed
 * there (no gate redirect), and capture a full-page screenshot as an
 * artifact. Param routes (/series/:id, /social/:platform), the fullscreen
 * editors and the OAuth callback are excluded — they need IDs / data.
 *
 * NOTE: routes reflect the CURRENT IA (pre-Phase-1). When Phase 1 lands the
 * Channels hub and the Create/Publish/Monitor regrouping, update this list.
 */
const ROUTES: { path: string; name: string }[] = [
  { path: '/', name: 'dashboard' },
  { path: '/series', name: 'series' },
  { path: '/episodes', name: 'episodes' },
  { path: '/audiobooks', name: 'audiobooks' },
  { path: '/assets', name: 'assets' },
  { path: '/templates', name: 'templates' },
  { path: '/character-packs', name: 'character-packs' },
  { path: '/calendar', name: 'calendar' },
  { path: '/channels', name: 'channels' },
  { path: '/youtube', name: 'youtube' },
  { path: '/youtube/library', name: 'youtube-library' },
  { path: '/jobs', name: 'jobs' },
  { path: '/usage', name: 'usage' },
  { path: '/logs', name: 'logs' },
  { path: '/cloud-gpu', name: 'cloud-gpu' },
  { path: '/settings', name: 'settings' },
  { path: '/help', name: 'help' },
  { path: '/login', name: 'login' },
];

// Stub the bootstrap endpoints so the license/login gates settle to a usable
// state without a live backend. Specific handlers are registered last so they
// win over the catch-all (Playwright matches most-recently-added first).
test.beforeEach(async ({ page }) => {
  await page.route('**/api/**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }),
  );
  await page.route('**/api/v1/auth/mode', (route) =>
    route.fulfill({ json: { team_mode: false, demo_mode: false } }),
  );
  await page.route('**/api/v1/auth/me', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: 'null' }),
  );
  await page.route('**/api/v1/license/status', (route) =>
    route.fulfill({ json: { state: 'active' } }),
  );
});

for (const { path, name } of ROUTES) {
  test(`route ${path} loads without redirect`, async ({ page }, testInfo) => {
    await page.goto(path);
    // Path-suffix match so baseURL/trailing-slash differences don't matter.
    const suffix = path === '/' ? '\\/' : path.replace(/\//g, '\\/');
    await expect(page).toHaveURL(new RegExp(`${suffix}$`));
    await page.screenshot({
      path: testInfo.outputPath(`route-${name}.png`),
      fullPage: true,
    });
  });
}
