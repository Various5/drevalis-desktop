import { configureAxe } from 'vitest-axe';

/**
 * Pre-configured axe runner for component-level a11y tests (Phase 5).
 *
 * Disables the three page-scoped *best-practice* rules that always fire on
 * isolated component renders — a single primitive isn't a whole page, so it
 * legitimately has no landmark / <main> / <h1>. Every other rule stays on,
 * including the WCAG A/AA structural checks we actually care about at the
 * component level: ``label``, ``button-name``, ``link-name``,
 * ``aria-valid-attr``, ``aria-required-attr``, ``role`` validity, etc.
 *
 * Note: ``color-contrast`` is disabled because there's no layout/paint under
 * jsdom to measure — left on, axe-core 4.11 still probes ``canvas.getContext``
 * (via its icon-ligature heuristic), which jsdom doesn't implement, flooding
 * the output with "Not implemented" errors. Contrast (WCAG 1.4.3, ≥4.5:1) is
 * therefore verified separately against the design tokens, not here.
 */
export const axe = configureAxe({
  rules: {
    region: { enabled: false },
    'landmark-one-main': { enabled: false },
    'page-has-heading-one': { enabled: false },
    'color-contrast': { enabled: false },
  },
});
