// Vitest global setup. Loaded once before any test runs.
//
// Adds @testing-library/jest-dom matchers (toBeInTheDocument, toHaveClass,
// etc.) so component tests can assert on rendered DOM ergonomically.
import '@testing-library/jest-dom/vitest';

// Accessibility matcher (Phase 5 a11y audit).
//
// We deliberately do NOT import vitest-axe's own ``toHaveNoViolations``: its
// 0.1.0 typings re-export the matcher through a multi-hop barrel that trips
// ``isolatedModules`` (TS1362). We only consume ``configureAxe`` from
// vitest-axe (see src/test/axe.ts), which is a clean value export. The matcher
// itself is trivial — assert axe found zero violations and print a readable
// report listing each rule, its impact, and the offending element when it did.
import { expect } from 'vitest';
import type { AxeResults, Result } from 'axe-core';

function formatViolations(violations: Result[]): string {
  return violations
    .map((v) => {
      const targets = v.nodes.map((n) => `      • ${n.target.join(' ')}`).join('\n');
      return `  [${v.impact ?? 'unknown'}] ${v.id}: ${v.help}\n    ${v.helpUrl}\n${targets}`;
    })
    .join('\n\n');
}

expect.extend({
  toHaveNoViolations(results: AxeResults) {
    const violations = results?.violations ?? [];
    const pass = violations.length === 0;
    return {
      pass,
      message: () =>
        pass
          ? 'expected accessibility violations, but found none'
          : `expected no accessibility violations but found ${violations.length}:\n\n${formatViolations(
              violations,
            )}`,
    };
  },
});

interface A11yMatchers<R = unknown> {
  toHaveNoViolations(): R;
}

declare module 'vitest' {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- must match Vitest's own Assertion<T = any> to merge.
  interface Assertion<T = any> extends A11yMatchers<T> {}
  interface AsymmetricMatchersContaining extends A11yMatchers {}
}
