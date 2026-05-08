/**
 * Theme system — bundled "personality" presets.
 *
 * Previously (v0.20.4 - v0.20.19) this module exposed an ``accentId``
 * that only swapped the accent color variables. Users asked for more —
 * each theme should change fonts, shadows, border radii, icon weights
 * alongside the color. This file now exposes ``themeId`` with 5 full
 * presets; each one sets:
 *
 * - ``--color-accent*`` / surface-tint variables (the v0.20.5 color
 *   system, kept).
 * - ``--font-display``  — headings + brand marks.
 * - ``--font-sans``     — body text.
 * - ``--radius-base``   — card + input corner radius.
 * - ``--shadow-style``  — ``flat | soft | glow | lifted``.
 * - ``--icon-stroke``   — inherited by every lucide icon via the CSS
 *                         ``svg { stroke-width: var(--icon-stroke); }``
 *                         rule applied globally.
 *
 * Adding a new preset: drop an entry in ``THEME_PRESETS`` with the same
 * shape. ``AppearanceSection`` auto-renders it.
 */

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ThemeMode = 'dark' | 'light';

export type ShadowStyle = 'flat' | 'soft' | 'glow' | 'lifted';

export interface ThemePreset {
  id: string;
  name: string;
  description: string;
  /** Accent hex — one color for dark mode, one for light. */
  accentDark: string;
  accentLight: string;
  accentDarkHover: string;
  accentLightHover: string;
  /** CSS font-family stack, including fallbacks. */
  fontDisplay: string;
  fontSans: string;
  /** Base corner radius in px. Scales via ``--radius-sm/md/lg``. */
  radiusBase: number;
  /** Stroke width passed to every lucide icon. Higher = bolder. */
  iconStroke: number;
  /** Shadow personality. See ``applyShadowStyle`` below. */
  shadowStyle: ShadowStyle;
}

export type ActivityDockPosition = 'bottom' | 'top' | 'left' | 'right';

// ---------------------------------------------------------------------------
// Presets — one bundle per "mood"
// ---------------------------------------------------------------------------

export const THEME_PRESETS: ThemePreset[] = [
  {
    id: 'studio',
    name: 'Studio',
    description: 'Balanced indigo · clean sans · soft shadows. Default.',
    accentDark: '#6366F1',
    accentLight: '#4F46E5',
    accentDarkHover: '#7C7EFF',
    accentLightHover: '#4338CA',
    fontDisplay: '"Outfit", system-ui, -apple-system, sans-serif',
    fontSans: '"Inter", "DM Sans", system-ui, -apple-system, sans-serif',
    radiusBase: 10,
    iconStroke: 2,
    shadowStyle: 'soft',
  },
  {
    id: 'cyber',
    name: 'Cyber',
    description: 'Electric cyan · geometric sans · neon glow · sharp corners.',
    accentDark: '#22D3EE',
    accentLight: '#06B6D4',
    accentDarkHover: '#67E8F9',
    accentLightHover: '#0891B2',
    fontDisplay: '"Space Grotesk", "Outfit", system-ui, sans-serif',
    fontSans: '"Inter", system-ui, -apple-system, sans-serif',
    radiusBase: 4,
    iconStroke: 1.75,
    shadowStyle: 'glow',
  },
  {
    id: 'warm',
    name: 'Warm',
    description: 'Amber gold · editorial serif · lifted shadows · pill corners.',
    accentDark: '#FBBF24',
    accentLight: '#F59E0B',
    accentDarkHover: '#FCD34D',
    accentLightHover: '#D97706',
    fontDisplay: '"Fraunces", "Playfair Display", Georgia, serif',
    fontSans: '"Inter", system-ui, -apple-system, sans-serif',
    radiusBase: 16,
    iconStroke: 2.25,
    shadowStyle: 'lifted',
  },
  {
    id: 'ink',
    name: 'Ink',
    description: 'Rose red · serif headings · measured rhythm · quiet shadows.',
    accentDark: '#FB7185',
    accentLight: '#E11D48',
    accentDarkHover: '#FDA4AF',
    accentLightHover: '#BE123C',
    fontDisplay: '"Fraunces", Georgia, serif',
    fontSans: '"Inter", system-ui, -apple-system, sans-serif',
    radiusBase: 8,
    iconStroke: 1.8,
    shadowStyle: 'soft',
  },
  {
    id: 'brutalist',
    name: 'Brutalist',
    description: 'Monospace · emerald · no shadows · zero radius.',
    accentDark: '#34D399',
    accentLight: '#10B981',
    accentDarkHover: '#6EE7B7',
    accentLightHover: '#059669',
    fontDisplay: '"IBM Plex Mono", "JetBrains Mono", ui-monospace, monospace',
    fontSans: '"IBM Plex Mono", "JetBrains Mono", ui-monospace, monospace',
    radiusBase: 0,
    iconStroke: 1.5,
    shadowStyle: 'flat',
  },
  {
    id: 'aurora',
    name: 'Aurora',
    description: 'Violet · DM Sans · soft shadows · friendly corners. Creative studio vibe.',
    accentDark: '#A78BFA',
    accentLight: '#8B5CF6',
    accentDarkHover: '#C4B5FD',
    accentLightHover: '#7C3AED',
    fontDisplay: '"DM Sans", "Outfit", system-ui, sans-serif',
    fontSans: '"Inter", "DM Sans", system-ui, -apple-system, sans-serif',
    radiusBase: 12,
    iconStroke: 2,
    shadowStyle: 'soft',
  },
];

// Back-compat shim: pages that imported ``ACCENT_COLORS`` still work —
// we expose the presets under that name with the shape the old code
// expected. The old pages that used this aren't part of the app's nav
// post-v0.20.20 (theme UI moved to Settings → Appearance) but leaving
// the export avoids breaking external references.
export const ACCENT_COLORS = THEME_PRESETS.map((p) => ({
  id: p.id,
  name: p.name,
  dark: p.accentDark,
  light: p.accentLight,
  darkHover: p.accentDarkHover,
  lightHover: p.accentLightHover,
}));
export interface AccentColor {
  id: string;
  name: string;
  dark: string;
  light: string;
  darkHover: string;
  lightHover: string;
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

interface ThemeContextValue {
  mode: ThemeMode;
  themeId: string;
  preset: ThemePreset;
  activityDock: ActivityDockPosition;

  setMode: (mode: ThemeMode) => void;
  setThemeId: (id: string) => void;
  setActivityDock: (p: ActivityDockPosition) => void;
  toggleMode: () => void;

  // Back-compat aliases — ``accent`` / ``setAccentId`` / ``accentId``
  // mirror the pre-v0.20.27 shape. New code should use ``preset`` and
  // ``setThemeId``.
  accent: AccentColor;
  accentId: string;
  setAccentId: (id: string) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

// ---------------------------------------------------------------------------
// Storage keys
// ---------------------------------------------------------------------------

const STORAGE_MODE_KEY = 'sf_theme_mode';
// Reuse the old accent key so users who had a preset picked keep it
// post-upgrade. Valid values are now preset IDs; any old accent ID
// that doesn't match a preset falls through to 'studio' on load.
const STORAGE_THEME_KEY = 'sf_theme_accent';
const STORAGE_DOCK_KEY = 'sf_activity_dock';

// ---------------------------------------------------------------------------
// Color-mix + shadow helpers
// ---------------------------------------------------------------------------

function hexToRgb(hex: string): { r: number; g: number; b: number } {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex);
  if (!m) return { r: 0, g: 0, b: 0 };
  const n = parseInt(m[1]!, 16);
  return { r: (n >> 16) & 0xff, g: (n >> 8) & 0xff, b: n & 0xff };
}

function mix(
  base: { r: number; g: number; b: number },
  accent: { r: number; g: number; b: number },
  ratio: number,
): string {
  const r = Math.round(base.r * (1 - ratio) + accent.r * ratio);
  const g = Math.round(base.g * (1 - ratio) + accent.g * ratio);
  const b = Math.round(base.b * (1 - ratio) + accent.b * ratio);
  return `rgb(${r}, ${g}, ${b})`;
}

function rgba(
  accent: { r: number; g: number; b: number },
  alpha: number,
): string {
  return `rgba(${accent.r}, ${accent.g}, ${accent.b}, ${alpha})`;
}

/** Shadow presets — each style produces a different CSS shadow token set. */
function applyShadowStyle(
  html: HTMLElement,
  style: ShadowStyle,
  accentRgb: { r: number; g: number; b: number },
  isLight: boolean,
): void {
  const base = isLight
    ? { softAlpha: 0.08, strongAlpha: 0.14 }
    : { softAlpha: 0.35, strongAlpha: 0.55 };

  switch (style) {
    case 'flat':
      html.style.setProperty('--shadow-sm', 'none');
      html.style.setProperty('--shadow', 'none');
      html.style.setProperty('--shadow-lg', 'none');
      html.style.setProperty('--shadow-accent-glow', 'none');
      break;
    case 'glow':
      html.style.setProperty('--shadow-sm', `0 0 8px ${rgba(accentRgb, 0.12)}`);
      html.style.setProperty(
        '--shadow',
        `0 0 20px ${rgba(accentRgb, 0.22)}, 0 0 2px ${rgba(accentRgb, 0.5)}`,
      );
      html.style.setProperty(
        '--shadow-lg',
        `0 0 40px ${rgba(accentRgb, 0.35)}, 0 0 4px ${rgba(accentRgb, 0.6)}`,
      );
      html.style.setProperty(
        '--shadow-accent-glow',
        `0 0 32px ${rgba(accentRgb, 0.45)}, 0 0 10px ${rgba(accentRgb, 0.3)}`,
      );
      break;
    case 'lifted':
      html.style.setProperty(
        '--shadow-sm',
        `0 2px 4px rgba(0,0,0,${base.softAlpha})`,
      );
      html.style.setProperty(
        '--shadow',
        `0 6px 16px -4px rgba(0,0,0,${base.softAlpha * 1.5})`,
      );
      html.style.setProperty(
        '--shadow-lg',
        `0 24px 48px -16px rgba(0,0,0,${base.strongAlpha})`,
      );
      html.style.setProperty(
        '--shadow-accent-glow',
        `0 8px 24px ${rgba(accentRgb, 0.28)}, 0 0 0 1px ${rgba(accentRgb, 0.15)}`,
      );
      break;
    case 'soft':
    default:
      html.style.setProperty(
        '--shadow-sm',
        `0 1px 2px rgba(0,0,0,${base.softAlpha * 0.6})`,
      );
      html.style.setProperty(
        '--shadow',
        `0 4px 12px -4px rgba(0,0,0,${base.softAlpha})`,
      );
      html.style.setProperty(
        '--shadow-lg',
        `0 16px 32px -12px rgba(0,0,0,${base.strongAlpha})`,
      );
      html.style.setProperty(
        '--shadow-accent-glow',
        `0 0 20px ${rgba(accentRgb, 0.2)}, 0 0 6px ${rgba(accentRgb, 0.12)}`,
      );
  }
}

// ---------------------------------------------------------------------------
// Apply theme to DOM
// ---------------------------------------------------------------------------

function applyTheme(mode: ThemeMode, preset: ThemePreset): void {
  const html = document.documentElement;

  // Mode class
  if (mode === 'light') {
    html.classList.add('light');
    html.classList.remove('dark');
  } else {
    html.classList.add('dark');
    html.classList.remove('light');
  }

  const isLight = mode === 'light';
  const accentHex = isLight ? preset.accentLight : preset.accentDark;
  const accentHoverHex = isLight ? preset.accentLightHover : preset.accentDarkHover;
  const accentRgb = hexToRgb(accentHex);

  // ── Accent ────────────────────────────────────────────────
  html.style.setProperty('--color-accent', accentHex);
  html.style.setProperty('--color-accent-hover', accentHoverHex);
  html.style.setProperty('--color-accent-active', accentHex);
  html.style.setProperty('--color-accent-muted', rgba(accentRgb, 0.1));
  html.style.setProperty('--color-accent-subtle', rgba(accentRgb, 0.2));
  html.style.setProperty('--color-border-accent', rgba(accentRgb, 0.3));

  // ── Surface tinting ──────────────────────────────────────
  const baseColor = isLight
    ? { r: 248, g: 249, b: 250 }
    : { r: 10, g: 10, b: 12 };
  const surfaceColor = isLight
    ? { r: 255, g: 255, b: 255 }
    : { r: 17, g: 17, b: 22 };
  const elevatedColor = isLight
    ? { r: 255, g: 255, b: 255 }
    : { r: 26, g: 26, b: 32 };
  const hoverColor = isLight
    ? { r: 241, g: 243, b: 245 }
    : { r: 36, g: 36, b: 44 };

  const tint = isLight ? 0.04 : 0.035;
  const hoverTint = isLight ? 0.07 : 0.065;

  html.style.setProperty('--color-bg-base', mix(baseColor, accentRgb, tint * 0.4));
  html.style.setProperty('--color-bg-surface', mix(surfaceColor, accentRgb, tint));
  html.style.setProperty('--color-bg-elevated', mix(elevatedColor, accentRgb, tint));
  html.style.setProperty('--color-bg-hover', mix(hoverColor, accentRgb, hoverTint));
  html.style.setProperty(
    '--color-bg-active',
    mix(hoverColor, accentRgb, hoverTint * 1.4),
  );

  const borderColor = isLight
    ? { r: 229, g: 231, b: 235 }
    : { r: 38, g: 38, b: 45 };
  html.style.setProperty('--color-border', mix(borderColor, accentRgb, 0.12));
  html.style.setProperty(
    '--color-border-hover',
    mix(borderColor, accentRgb, 0.22),
  );

  // ── Preset-scoped tokens (v0.20.27) ──────────────────────
  html.style.setProperty('--font-display', preset.fontDisplay);
  html.style.setProperty('--font-sans', preset.fontSans);

  // Radii scale off the preset base so buttons/inputs/pills all keep
  // their proportions when switching themes.
  const r = preset.radiusBase;
  html.style.setProperty('--radius-sm', `${Math.max(0, r - 4)}px`);
  html.style.setProperty('--radius', `${r}px`);
  html.style.setProperty('--radius-md', `${r}px`);
  html.style.setProperty('--radius-lg', `${r + 4}px`);
  html.style.setProperty('--radius-xl', `${r + 10}px`);
  // Full — pills stay fully round for brutalist/flat too since a
  // pill-shaped chip is a semantic shape, not a theme choice.
  html.style.setProperty('--radius-full', '9999px');

  // Icon stroke applied globally via the rule in globals.css:
  //   svg { stroke-width: var(--icon-stroke-width); }
  html.style.setProperty('--icon-stroke-width', String(preset.iconStroke));

  // Tag the theme on <html> so CSS can opt specific styles in/out per
  // preset (e.g. ``html[data-theme="brutalist"] .card { border-width: 2px; }``).
  html.dataset.theme = preset.id;

  applyShadowStyle(html, preset.shadowStyle, accentRgb, isLight);
}

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

function safeGet(key: string): string | null {
  try {
    return typeof window !== 'undefined' ? window.localStorage.getItem(key) : null;
  } catch {
    return null;
  }
}
function safeSet(key: string, value: string): void {
  try {
    if (typeof window !== 'undefined') window.localStorage.setItem(key, value);
  } catch {
    /* persistence is best-effort */
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>(() => {
    const stored = safeGet(STORAGE_MODE_KEY);
    return stored === 'light' || stored === 'dark' ? stored : 'dark';
  });

  const [themeId, setThemeIdState] = useState<string>(() => {
    const stored = safeGet(STORAGE_THEME_KEY) ?? 'studio';
    // Old accent IDs ('teal', 'blue', 'amber', ...) — remap to the
    // closest preset so users aren't bounced to the default silently.
    const legacyMap: Record<string, string> = {
      teal: 'studio',
      blue: 'studio',
      purple: 'studio',
      rose: 'ink',
      amber: 'warm',
      emerald: 'brutalist',
      cyan: 'cyber',
      orange: 'warm',
    };
    const valid = THEME_PRESETS.some((p) => p.id === stored);
    return valid ? stored : (legacyMap[stored] ?? 'studio');
  });

  const [activityDock, setActivityDockState] = useState<ActivityDockPosition>(() => {
    const stored = safeGet(STORAGE_DOCK_KEY);
    return (['bottom', 'top', 'left', 'right'] as const).includes(
      stored as ActivityDockPosition,
    )
      ? (stored as ActivityDockPosition)
      : 'bottom';
  });

  const preset =
    THEME_PRESETS.find((p) => p.id === themeId) ?? THEME_PRESETS[0]!;

  const setMode = useCallback((m: ThemeMode) => {
    setModeState(m);
    safeSet(STORAGE_MODE_KEY, m);
  }, []);

  const setThemeId = useCallback((id: string) => {
    setThemeIdState(id);
    safeSet(STORAGE_THEME_KEY, id);
  }, []);

  // Alias for back-compat.
  const setAccentId = setThemeId;

  const setActivityDock = useCallback((p: ActivityDockPosition) => {
    setActivityDockState(p);
    safeSet(STORAGE_DOCK_KEY, p);
  }, []);

  const toggleMode = useCallback(() => {
    setMode(mode === 'dark' ? 'light' : 'dark');
  }, [mode, setMode]);

  useEffect(() => {
    applyTheme(mode, preset);
  }, [mode, preset]);

  useEffect(() => {
    document.documentElement.dataset.activityDock = activityDock;
  }, [activityDock]);

  const accent: AccentColor = {
    id: preset.id,
    name: preset.name,
    dark: preset.accentDark,
    light: preset.accentLight,
    darkHover: preset.accentDarkHover,
    lightHover: preset.accentLightHover,
  };

  return (
    <ThemeContext.Provider
      value={{
        mode,
        themeId,
        preset,
        activityDock,
        setMode,
        setThemeId,
        setActivityDock,
        toggleMode,
        accent,
        accentId: themeId,
        setAccentId,
      }}
    >
      {children}
    </ThemeContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme must be used within <ThemeProvider>');
  return ctx;
}
