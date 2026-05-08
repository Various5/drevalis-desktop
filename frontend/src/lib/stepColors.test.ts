// Tests for the canonical step colour palette + ordering.
//
// stepColors.ts is the single source of truth for which Tailwind class
// each pipeline step uses. A typo in one of the records would silently
// render a step in the wrong colour across half the app.

import { describe, it, expect } from 'vitest';
import {
  STEP_TEXT,
  STEP_BG,
  STEP_MUTED,
  STEP_ORDER,
  isKnownStep,
  type StepName,
} from './stepColors';

describe('STEP_ORDER', () => {
  it('contains exactly the six pipeline steps in pipeline order', () => {
    expect(STEP_ORDER).toEqual([
      'script',
      'voice',
      'scenes',
      'captions',
      'assembly',
      'thumbnail',
    ]);
  });

  it('has length 6 (no drift from the backend pipeline)', () => {
    expect(STEP_ORDER).toHaveLength(6);
  });
});

describe('STEP_TEXT / STEP_BG / STEP_MUTED', () => {
  it.each(STEP_ORDER)('STEP_TEXT.%s uses the matching text-step-* class', (step) => {
    expect(STEP_TEXT[step]).toBe(`text-step-${step}`);
  });

  it.each(STEP_ORDER)('STEP_BG.%s uses the matching bg-step-* class', (step) => {
    expect(STEP_BG[step]).toBe(`bg-step-${step}`);
  });

  it.each(STEP_ORDER)('STEP_MUTED.%s uses the matching bg-step-muted-* class', (step) => {
    expect(STEP_MUTED[step]).toBe(`bg-step-muted-${step}`);
  });

  it('every step in STEP_ORDER has an entry in every record', () => {
    for (const step of STEP_ORDER) {
      expect(STEP_TEXT).toHaveProperty(step);
      expect(STEP_BG).toHaveProperty(step);
      expect(STEP_MUTED).toHaveProperty(step);
    }
  });

  it('records have no extra keys beyond STEP_ORDER', () => {
    expect(Object.keys(STEP_TEXT).sort()).toEqual([...STEP_ORDER].sort());
    expect(Object.keys(STEP_BG).sort()).toEqual([...STEP_ORDER].sort());
    expect(Object.keys(STEP_MUTED).sort()).toEqual([...STEP_ORDER].sort());
  });
});

describe('isKnownStep', () => {
  it.each(STEP_ORDER)('returns true for the canonical step "%s"', (step) => {
    expect(isKnownStep(step)).toBe(true);
  });

  it('returns false for unknown values', () => {
    expect(isKnownStep('upload')).toBe(false);
    expect(isKnownStep('')).toBe(false);
    expect(isKnownStep('SCRIPT')).toBe(false); // case-sensitive
  });

  it('narrows the type to StepName', () => {
    const candidate: string = 'voice';
    if (isKnownStep(candidate)) {
      // Compile-time check: candidate is now StepName
      const _typed: StepName = candidate;
      expect(_typed).toBe('voice');
    }
  });
});
