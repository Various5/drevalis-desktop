/**
 * Design-token contrast audit (Phase 5 a11y, WCAG 2.1 SC 1.4.3 / 1.4.11).
 *
 * axe-core can't measure contrast under jsdom (no paint), so this is the other
 * half of the a11y net: it reads the real CSS custom properties out of
 * globals.css for both the default dark (``:root``) and light (``html.light``)
 * themes, then asserts every meaningful foreground/background pairing clears
 * its WCAG AA threshold. Parsing the stylesheet directly means a token edit
 * that drops below AA fails *this* test — the values can't silently drift.
 *
 * Scope: the base/default theme only. Per-preset accent overrides (lib/theme)
 * and user-chosen accents are a separate, larger audit.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { ratio, AA_NORMAL } from '@/lib/contrast';

// Read the real stylesheet at test time (vitest runs with cwd at the frontend
// root). We can't use Vite's ?raw import here because the test config sets
// ``css: false``, which stubs CSS imports to empty. Node built-ins are typed
// by src/test/node-test-env.d.ts (the app tsconfig omits @types/node).
const css = readFileSync(resolve(process.cwd(), 'src/styles/globals.css'), 'utf8');

/** Extract a `{ ... }` rule body by selector, then parse its --color-* vars. */
function parseTokens(selector: string): Record<string, string> {
  const re = new RegExp(`${selector}\\s*\\{([^}]*)\\}`);
  const body = css.match(re)?.[1];
  if (!body) throw new Error(`Could not find CSS block for selector "${selector}"`);

  const map: Record<string, string> = {};
  for (const m of body.matchAll(/--([\w-]+):\s*([^;]+);/g)) {
    map[m[1]!] = m[2]!.trim();
  }
  // Resolve one level of var(--x) aliases (e.g. text-muted -> text-tertiary).
  for (const [k, v] of Object.entries(map)) {
    const ref = v.match(/^var\(--([\w-]+)\)/);
    if (ref && map[ref[1]!]) map[k] = map[ref[1]!]!;
  }
  return map;
}

const dark = parseTokens(':root');
const light = parseTokens('html\\.light');

type Pair = [label: string, fgVar: string, bgVar: string, threshold?: number];

// Each entry pairs a foreground token with a background token it actually
// renders on in the app. Threshold defaults to AA normal-text (4.5:1); the
// few genuinely large-text-only / UI-component pairings pass it explicitly.
const darkPairs: Pair[] = [
  ['primary text / base', 'color-text-primary', 'color-bg-base'],
  ['primary text / surface', 'color-text-primary', 'color-bg-surface'],
  ['primary text / elevated', 'color-text-primary', 'color-bg-elevated'],
  ['secondary text / base', 'color-text-secondary', 'color-bg-base'],
  ['secondary text / surface', 'color-text-secondary', 'color-bg-surface'],
  ['tertiary text / base', 'color-text-tertiary', 'color-bg-base'],
  ['tertiary text / surface', 'color-text-tertiary', 'color-bg-surface'],
  ['tertiary text / elevated', 'color-text-tertiary', 'color-bg-elevated'],
  ['muted text / surface', 'color-text-muted', 'color-bg-surface'],
  ['on-accent text / accent fill', 'color-text-on-accent', 'color-accent'],
  ['on-accent text / accent-hover fill', 'color-text-on-accent', 'color-accent-hover'],
  ['on-accent text / accent-active fill', 'color-text-on-accent', 'color-accent-active'],
  ['accent as text / base', 'color-accent', 'color-bg-base'],
  ['accent as text / surface', 'color-accent', 'color-bg-surface'],
  ['success text / surface', 'color-success', 'color-bg-surface'],
  ['warning text / surface', 'color-warning', 'color-bg-surface'],
  ['error text / surface', 'color-error', 'color-bg-surface'],
  ['info text / surface', 'color-info', 'color-bg-surface'],
];

const lightPairs: Pair[] = [
  ['primary text / base', 'color-text-primary', 'color-bg-base'],
  ['primary text / surface', 'color-text-primary', 'color-bg-surface'],
  ['secondary text / base', 'color-text-secondary', 'color-bg-base'],
  ['secondary text / surface', 'color-text-secondary', 'color-bg-surface'],
  ['tertiary text / base', 'color-text-tertiary', 'color-bg-base'],
  ['tertiary text / surface', 'color-text-tertiary', 'color-bg-surface'],
  ['on-accent text / accent fill', 'color-text-on-accent', 'color-accent'],
  ['on-accent text / accent-hover fill', 'color-text-on-accent', 'color-accent-hover'],
  ['on-accent text / accent-active fill', 'color-text-on-accent', 'color-accent-active'],
  ['accent as text / base', 'color-accent', 'color-bg-base'],
  ['accent as text / surface', 'color-accent', 'color-bg-surface'],
  ['success text / surface', 'color-success', 'color-bg-surface'],
  ['warning text / surface', 'color-warning', 'color-bg-surface'],
  ['error text / surface', 'color-error', 'color-bg-surface'],
  ['info text / surface', 'color-info', 'color-bg-surface'],
];

function check(tokens: Record<string, string>, [label, fgVar, bgVar, threshold = AA_NORMAL]: Pair) {
  const fg = tokens[fgVar];
  const bg = tokens[bgVar];
  expect(fg, `missing token --${fgVar}`).toBeTruthy();
  expect(bg, `missing token --${bgVar}`).toBeTruthy();
  const r = ratio(fg!, bg!);
  // The message carries the ratio so a failure reads e.g.
  // "warning text / surface: 2.15 < 4.5 (#F59E0B on #FFFFFF)".
  expect(
    r,
    `${label}: ${r.toFixed(2)} < ${threshold} (${fg} on ${bg})`,
  ).toBeGreaterThanOrEqual(threshold);
}

describe('design tokens — WCAG AA contrast (dark / :root)', () => {
  it.each(darkPairs)('%s', (...pair) => check(dark, pair));
});

describe('design tokens — WCAG AA contrast (light / html.light)', () => {
  it.each(lightPairs)('%s', (...pair) => check(light, pair));
});
