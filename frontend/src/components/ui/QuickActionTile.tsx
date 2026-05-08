import type { ReactNode } from 'react';

// ---------------------------------------------------------------------------
// QuickActionTile (Phase 2.4)
// ---------------------------------------------------------------------------
//
// Replaces the four hand-rolled <button> blocks on the Dashboard
// quick-actions row. The previous markup duplicated ~12 utility
// classes per tile and used different accent-tinted background
// classes (``bg-accent/[0.08]``, ``bg-success/[0.08]``, ``bg-info/[0.08]``,
// ``bg-warning/[0.08]``); pulling these into a typed prop locks the
// hover / focus / shadow contract so all four tiles render the same
// way.

export type TileAccent = 'accent' | 'success' | 'info' | 'warning';

interface QuickActionTileProps {
  icon: ReactNode;
  label: string;
  hint: string;
  accent: TileAccent;
  onClick: () => void;
  ariaLabel?: string;
}

const ACCENT_BG: Record<TileAccent, string> = {
  accent: 'bg-accent/[0.08]',
  success: 'bg-success/[0.08]',
  info: 'bg-info/[0.08]',
  warning: 'bg-warning/[0.08]',
};

const ACCENT_TEXT: Record<TileAccent, string> = {
  accent: 'text-accent',
  success: 'text-success',
  info: 'text-info',
  warning: 'text-warning',
};

export function QuickActionTile({
  icon,
  label,
  hint,
  accent,
  onClick,
  ariaLabel,
}: QuickActionTileProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={ariaLabel ?? label}
      className="flex flex-col items-center gap-2 p-4 bg-bg-surface/60 backdrop-blur-sm border border-white/[0.04] rounded-xl text-center transition-all duration-normal hover:bg-bg-surface/80 hover:border-white/[0.08] hover:shadow-card-hover group"
    >
      <div
        className={[
          'w-10 h-10 rounded-xl flex items-center justify-center icon-hover',
          ACCENT_BG[accent],
          ACCENT_TEXT[accent],
        ].join(' ')}
      >
        {icon}
      </div>
      <span className="text-sm font-display font-medium text-txt-primary">{label}</span>
      <span className="text-xs text-txt-tertiary">{hint}</span>
    </button>
  );
}

export type { QuickActionTileProps };
