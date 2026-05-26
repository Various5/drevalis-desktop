import { describe, it, expect } from 'vitest';
import { parseHex, composite, contrastRatio, ratio, AA_NORMAL } from './contrast';

describe('contrast math', () => {
  it('parses #RGB, #RRGGBB and #RRGGBBAA', () => {
    expect(parseHex('#fff')).toEqual({ r: 255, g: 255, b: 255, a: 1 });
    expect(parseHex('#0A0A0B')).toEqual({ r: 10, g: 10, b: 11, a: 1 });
    expect(parseHex('#00D4AA1A').a).toBeCloseTo(0.102, 2);
  });

  it('throws on garbage hex', () => {
    expect(() => parseHex('not-a-color')).toThrow();
    expect(() => parseHex('#12')).toThrow();
  });

  it('black on white is the maximum 21:1', () => {
    expect(ratio('#000000', '#FFFFFF')).toBeCloseTo(21, 1);
  });

  it('identical colors are 1:1', () => {
    expect(ratio('#3344AA', '#3344AA')).toBeCloseTo(1, 5);
  });

  it('composites a translucent fg over an opaque bg', () => {
    // 50% white over black → mid grey (#808080-ish).
    const c = composite({ r: 255, g: 255, b: 255, a: 0.5 }, { r: 0, g: 0, b: 0, a: 1 });
    expect(c).toEqual({ r: 128, g: 128, b: 128, a: 1 });
  });

  it('matches a known WCAG reference pair', () => {
    // #767676 on #FFFFFF is the canonical "exactly AA" grey ≈ 4.54:1.
    expect(ratio('#767676', '#FFFFFF')).toBeGreaterThanOrEqual(AA_NORMAL);
    expect(ratio('#777777', '#FFFFFF')).toBeLessThan(AA_NORMAL); // just over the line fails
  });

  it('contrastRatio is symmetric', () => {
    const a = parseHex('#123456');
    const b = parseHex('#abcdef');
    expect(contrastRatio(a, b)).toBeCloseTo(contrastRatio(b, a), 10);
  });
});
