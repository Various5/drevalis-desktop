/**
 * Appearance — theme presets (v0.20.27).
 *
 * Each "theme" is a coherent preset: accent color, display font, body
 * font, border radius, shadow style, and icon stroke width bundled
 * together. Users pick a mood; the whole app picks up the rest.
 *
 * This section also hosts the dark/light mode toggle and the
 * Activity Monitor position picker (moved here from the sidebar in
 * v0.20.3 so navigation surfaces stay workflow-focused).
 */

import {
  Sun,
  Moon,
  PanelBottom,
  PanelTop,
  PanelLeft,
  PanelRight,
  Sparkles,
  Check,
} from 'lucide-react';
import { Card } from '@/components/ui/Card';
import {
  useTheme,
  THEME_PRESETS,
  type ActivityDockPosition,
  type ThemePreset,
} from '@/lib/theme';

const DOCK_OPTIONS: Array<{
  id: ActivityDockPosition;
  label: string;
  icon: typeof PanelBottom;
  help: string;
}> = [
  {
    id: 'bottom',
    label: 'Bottom',
    icon: PanelBottom,
    help: 'Classic task-bar strip across the bottom.',
  },
  {
    id: 'top',
    label: 'Top',
    icon: PanelTop,
    help: 'Pinned above the header.',
  },
  {
    id: 'left',
    label: 'Left rail',
    icon: PanelLeft,
    help: 'Full-height rail on the left.',
  },
  {
    id: 'right',
    label: 'Right rail',
    icon: PanelRight,
    help: 'Full-height rail on the right.',
  },
];

function PresetCard({
  preset,
  isActive,
  isLight,
  onSelect,
}: {
  preset: ThemePreset;
  isActive: boolean;
  isLight: boolean;
  onSelect: () => void;
}) {
  const accent = isLight ? preset.accentLight : preset.accentDark;
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={isActive}
      className={[
        'relative text-left p-4 transition-all border overflow-hidden',
        'hover:border-accent/40',
        isActive
          ? 'border-accent bg-accent-muted/30 shadow-[0_0_0_3px_rgba(99,102,241,0.15)]'
          : 'border-border bg-bg-elevated hover:bg-bg-hover',
      ].join(' ')}
      style={{
        borderRadius: `${preset.radiusBase + 4}px`,
        boxShadow: isActive
          ? `0 0 0 3px ${accent}20, 0 8px 24px -12px ${accent}40`
          : undefined,
      }}
    >
      {isActive && (
        <div
          className="absolute top-2 right-2 w-5 h-5 rounded-full flex items-center justify-center"
          style={{ backgroundColor: accent }}
        >
          <Check size={12} className="text-white" strokeWidth={3} />
        </div>
      )}

      {/* Display-font sample — the single most identity-defining bit
          of any preset. Set inline so the swap is visible without
          activating the preset. */}
      <div
        className="text-xl font-bold mb-1 leading-tight"
        style={{
          fontFamily: preset.fontDisplay,
          color: accent,
        }}
      >
        {preset.name}
      </div>
      <div className="text-[11px] text-txt-secondary mb-3 leading-snug">
        {preset.description}
      </div>

      {/* Visual chips — accent pill + radius block + icon stroke
          sample — so the user can see the personality without the
          marketing description. */}
      <div className="flex items-center gap-2 flex-wrap">
        <span
          className="inline-block h-2 w-2 rounded-full shrink-0"
          style={{ backgroundColor: accent }}
          aria-hidden
        />
        <span
          className="px-2 py-0.5 text-[10px] font-medium"
          style={{
            backgroundColor: `${accent}1f`,
            color: accent,
            borderRadius: `${preset.radiusBase}px`,
          }}
        >
          {preset.radiusBase === 0
            ? 'sharp'
            : preset.radiusBase <= 6
              ? 'crisp'
              : preset.radiusBase <= 12
                ? 'soft'
                : 'pill'}
        </span>
        <span
          className="text-[10px] text-txt-muted"
          style={{ fontFamily: preset.fontSans }}
        >
          body · {preset.fontSans.split(',')[0]?.replace(/"/g, '')}
        </span>
        <Sparkles
          size={12}
          strokeWidth={preset.iconStroke}
          style={{ color: accent }}
        />
      </div>
    </button>
  );
}

export function AppearanceSection() {
  const { mode, toggleMode, themeId, setThemeId, activityDock, setActivityDock } =
    useTheme();
  const isLight = mode === 'light';

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-lg font-semibold text-txt-primary">Appearance</h3>
        <p className="text-xs text-txt-secondary mt-1">
          Theme presets bundle accent color, display font, border radius,
          and shadow style. Mode (dark/light) and Activity Monitor position
          are independent choices.
        </p>
      </div>

      {/* ── Color mode ─────────────────────────────────────────── */}
      <Card className="p-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h4 className="text-sm font-semibold text-txt-primary">Color mode</h4>
            <p className="text-xs text-txt-secondary mt-1">
              {isLight
                ? 'Currently light — high contrast for bright studios.'
                : 'Currently dark — easier on the eyes for long sessions.'}
            </p>
          </div>
          <button
            type="button"
            onClick={toggleMode}
            className="flex items-center gap-2 rounded-md border border-border bg-bg-elevated px-3 py-2 text-sm font-medium text-txt-primary hover:bg-bg-hover transition-colors"
            aria-label={`Switch to ${isLight ? 'dark' : 'light'} mode`}
          >
            {isLight ? <Moon size={14} /> : <Sun size={14} />}
            {isLight ? 'Switch to dark' : 'Switch to light'}
          </button>
        </div>
      </Card>

      {/* ── Theme presets ──────────────────────────────────────── */}
      <Card className="p-5">
        <div className="mb-4">
          <h4 className="text-sm font-semibold text-txt-primary">Theme preset</h4>
          <p className="text-xs text-txt-secondary mt-1">
            Pick a mood — each preset changes fonts, colors, radii, shadows,
            and icon weight together. Click a card to apply instantly.
          </p>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {THEME_PRESETS.map((p) => (
            <PresetCard
              key={p.id}
              preset={p}
              isActive={themeId === p.id}
              isLight={isLight}
              onSelect={() => setThemeId(p.id)}
            />
          ))}
        </div>
      </Card>

      {/* ── Activity Monitor dock ─────────────────────────────── */}
      <Card className="p-5">
        <h4 className="text-sm font-semibold text-txt-primary">
          Activity Monitor position
        </h4>
        <p className="text-xs text-txt-secondary mt-1 mb-4">
          Where the background-jobs bar lives. Top/bottom show a compact tray;
          left/right show a collapsible full-height rail.
        </p>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          {DOCK_OPTIONS.map((opt) => {
            const isActive = activityDock === opt.id;
            const Icon = opt.icon;
            return (
              <button
                key={opt.id}
                type="button"
                onClick={() => setActivityDock(opt.id)}
                className={[
                  'flex flex-col items-center gap-2 rounded-md border px-3 py-3 text-xs font-medium transition-all text-left',
                  isActive
                    ? 'border-accent bg-accent-muted text-txt-primary'
                    : 'border-border bg-bg-elevated text-txt-secondary hover:border-border-strong',
                ].join(' ')}
                aria-pressed={isActive}
              >
                <Icon size={18} className={isActive ? 'text-accent' : 'text-txt-tertiary'} />
                <span className="text-txt-primary">{opt.label}</span>
                <span className="text-[11px] text-txt-muted leading-snug">
                  {opt.help}
                </span>
              </button>
            );
          })}
        </div>
      </Card>
    </div>
  );
}

export default AppearanceSection;
