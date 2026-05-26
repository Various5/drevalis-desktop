/**
 * WCAG 2.1 contrast math (Phase 5 a11y).
 *
 * Used by the design-token contrast audit (src/styles/tokens.a11y.test.ts) to
 * verify foreground/background token pairs meet WCAG AA, and available at
 * runtime for validating user-chosen accent colors against the surfaces they
 * sit on. Pure functions, no DOM — safe anywhere.
 *
 * Reference: https://www.w3.org/TR/WCAG21/#dfn-contrast-ratio
 */

export interface Rgb {
  r: number;
  g: number;
  b: number;
  /** 0–1 alpha; 1 (opaque) when the source had no alpha channel. */
  a: number;
}

/**
 * Parse a #RGB, #RRGGBB, or #RRGGBBAA hex string into RGBA (0–255 channels,
 * 0–1 alpha). Throws on anything it can't parse so a typo'd token surfaces
 * loudly in the audit rather than silently scoring 0.
 */
export function parseHex(hex: string): Rgb {
  const h = hex.trim().replace(/^#/, '');
  let r: number;
  let g: number;
  let b: number;
  let a = 1;
  if (h.length === 3) {
    r = parseInt(h[0]! + h[0]!, 16);
    g = parseInt(h[1]! + h[1]!, 16);
    b = parseInt(h[2]! + h[2]!, 16);
  } else if (h.length === 6 || h.length === 8) {
    r = parseInt(h.slice(0, 2), 16);
    g = parseInt(h.slice(2, 4), 16);
    b = parseInt(h.slice(4, 6), 16);
    if (h.length === 8) a = parseInt(h.slice(6, 8), 16) / 255;
  } else {
    throw new Error(`Unparseable hex color: "${hex}"`);
  }
  if ([r, g, b].some((c) => Number.isNaN(c))) {
    throw new Error(`Unparseable hex color: "${hex}"`);
  }
  return { r, g, b, a };
}

/**
 * Composite a (possibly translucent) foreground over an opaque background,
 * returning an opaque color. Token "muted" backgrounds are e.g. the accent at
 * 10% alpha, so the real surface a user sees is the muted tint *over* the
 * panel — this resolves that to the actual rendered color.
 */
export function composite(fg: Rgb, opaqueBg: Rgb): Rgb {
  const a = fg.a;
  return {
    r: Math.round(fg.r * a + opaqueBg.r * (1 - a)),
    g: Math.round(fg.g * a + opaqueBg.g * (1 - a)),
    b: Math.round(fg.b * a + opaqueBg.b * (1 - a)),
    a: 1,
  };
}

/** WCAG relative luminance of an opaque color (alpha is ignored). */
export function relativeLuminance({ r, g, b }: Rgb): number {
  const lin = (c: number) => {
    const cs = c / 255;
    return cs <= 0.03928 ? cs / 12.92 : ((cs + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

/**
 * Contrast ratio between two colors (1–21). Translucent inputs should be
 * composited first; an alpha < 1 here is treated as-is on its own luminance,
 * which is rarely what you want — pass opaque colors.
 */
export function contrastRatio(a: Rgb, b: Rgb): number {
  const la = relativeLuminance(a);
  const lb = relativeLuminance(b);
  const lighter = Math.max(la, lb);
  const darker = Math.min(la, lb);
  return (lighter + 0.05) / (darker + 0.05);
}

/**
 * Convenience: contrast ratio between two color strings, compositing the
 * foreground over the (assumed opaque) background when it has alpha.
 */
export function ratio(fgHex: string, bgHex: string): number {
  const bg = parseHex(bgHex);
  const fgRaw = parseHex(fgHex);
  const fg = fgRaw.a < 1 ? composite(fgRaw, bg) : fgRaw;
  return contrastRatio(fg, bg);
}

/** WCAG AA thresholds. Normal text 4.5:1; large text / UI components 3:1. */
export const AA_NORMAL = 4.5;
export const AA_LARGE = 3;
