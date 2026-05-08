import { useEffect, useState } from 'react';
import {
  Type,
  Square,
  Scissors,
  Trash2,
  ZoomIn,
  ZoomOut,
  Keyboard,
  Image as ImageIcon,
  Sticker,
  Circle,
  Slash,
} from 'lucide-react';

// ─── Props ──────────────────────────────────────────────────────────

export interface ToolsRailProps {
  onAddText: (preset: 'title' | 'subtitle' | 'caption' | 'lowerThird') => void;
  onAddShape: (shape: 'rect' | 'circle' | 'line') => void;
  onOpenAssetsTab: () => void;
  onOpenStampsTab: () => void;
  onSplit: () => void;
  onDelete: () => void;
  snapEnabled: boolean;
  snapStep: number;
  onToggleSnap: () => void;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onOpenShortcuts: () => void;
  hasSelection: boolean;
}

// ─── ToolsRail ──────────────────────────────────────────────────────

export function ToolsRail({
  onAddText,
  onAddShape,
  onOpenAssetsTab,
  onOpenStampsTab,
  onSplit,
  onDelete,
  snapEnabled,
  snapStep,
  onToggleSnap,
  onZoomIn,
  onZoomOut,
  onOpenShortcuts,
  hasSelection,
}: ToolsRailProps) {
  const [activeFlyout, setActiveFlyout] = useState<'text' | 'shape' | null>(
    null,
  );

  // Close flyout on outside click.
  useEffect(() => {
    if (!activeFlyout) return;
    const handler = () => setActiveFlyout(null);
    window.addEventListener('click', handler);
    return () => window.removeEventListener('click', handler);
  }, [activeFlyout]);

  return (
    <div className="w-14 shrink-0 border-r border-border bg-bg-surface flex flex-col py-2 gap-1">
      <ToolButton
        icon={Type}
        label="Text"
        active={activeFlyout === 'text'}
        onClick={(e) => {
          e.stopPropagation();
          setActiveFlyout((prev) => (prev === 'text' ? null : 'text'));
        }}
        flyout={
          activeFlyout === 'text' ? (
            <Flyout>
              <FlyoutItem
                label="Title"
                description="Large centered title"
                onClick={() => {
                  onAddText('title');
                  setActiveFlyout(null);
                }}
              />
              <FlyoutItem
                label="Subtitle"
                description="Medium centered text"
                onClick={() => {
                  onAddText('subtitle');
                  setActiveFlyout(null);
                }}
              />
              <FlyoutItem
                label="Caption"
                description="Text with background box"
                onClick={() => {
                  onAddText('caption');
                  setActiveFlyout(null);
                }}
              />
              <FlyoutItem
                label="Lower third"
                description="Caption style anchored to bottom"
                onClick={() => {
                  onAddText('lowerThird');
                  setActiveFlyout(null);
                }}
              />
            </Flyout>
          ) : null
        }
      />
      <ToolButton
        icon={Square}
        label="Shape"
        active={activeFlyout === 'shape'}
        onClick={(e) => {
          e.stopPropagation();
          setActiveFlyout((prev) => (prev === 'shape' ? null : 'shape'));
        }}
        flyout={
          activeFlyout === 'shape' ? (
            <Flyout>
              <FlyoutItem
                icon={Square}
                label="Rectangle"
                onClick={() => {
                  onAddShape('rect');
                  setActiveFlyout(null);
                }}
              />
              <FlyoutItem
                icon={Circle}
                label="Circle"
                onClick={() => {
                  onAddShape('circle');
                  setActiveFlyout(null);
                }}
              />
              <FlyoutItem
                icon={Slash}
                label="Line"
                onClick={() => {
                  onAddShape('line');
                  setActiveFlyout(null);
                }}
              />
            </Flyout>
          ) : null
        }
      />
      <ToolButton
        icon={ImageIcon}
        label="Image (assets)"
        onClick={onOpenAssetsTab}
      />
      <ToolButton
        icon={Sticker}
        label="Stamps & effects"
        onClick={onOpenStampsTab}
      />
      <div className="mx-2 my-1 h-px bg-border" />
      <ToolButton
        icon={Scissors}
        label="Split"
        onClick={onSplit}
        disabled={!hasSelection}
      />
      <ToolButton
        icon={Trash2}
        label="Delete"
        onClick={onDelete}
        disabled={!hasSelection}
        danger
      />
      <div className="flex-1" />
      <ToolButton
        icon={ZoomIn}
        label="Zoom in"
        onClick={onZoomIn}
      />
      <ToolButton
        icon={ZoomOut}
        label="Zoom out"
        onClick={onZoomOut}
      />
      <button
        type="button"
        onClick={onToggleSnap}
        title={`Snap ${snapStep}s ${snapEnabled ? 'on' : 'off'}`}
        className={[
          'mx-2 rounded-md text-[9px] font-semibold uppercase tracking-wider py-1',
          snapEnabled
            ? 'bg-accent/15 text-accent border border-accent/30'
            : 'bg-bg-elevated text-txt-tertiary border border-border hover:text-txt-primary',
        ].join(' ')}
      >
        {snapStep}s
      </button>
      <ToolButton
        icon={Keyboard}
        label="Shortcuts (?)"
        onClick={onOpenShortcuts}
      />
    </div>
  );
}

// ─── ToolButton ─────────────────────────────────────────────────────

export function ToolButton({
  icon: Icon,
  label,
  onClick,
  active,
  disabled,
  danger,
  flyout,
}: {
  icon: typeof Type;
  label: string;
  onClick: (e: React.MouseEvent) => void;
  active?: boolean;
  disabled?: boolean;
  danger?: boolean;
  flyout?: React.ReactNode;
}) {
  return (
    <div className="relative flex justify-center">
      <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        title={label}
        aria-label={label}
        className={[
          'w-10 h-10 rounded-md flex items-center justify-center transition-colors duration-fast',
          disabled
            ? 'text-txt-muted cursor-not-allowed'
            : active
              ? 'bg-accent/15 text-accent'
              : danger
                ? 'text-txt-secondary hover:bg-error/10 hover:text-error'
                : 'text-txt-secondary hover:bg-bg-hover hover:text-txt-primary',
        ].join(' ')}
      >
        <Icon size={16} />
      </button>
      {flyout}
    </div>
  );
}

// ─── Flyout ─────────────────────────────────────────────────────────

export function Flyout({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="absolute left-full top-0 ml-2 min-w-56 rounded-lg border border-border bg-bg-surface shadow-xl z-30 py-1 text-sm"
      onClick={(e) => e.stopPropagation()}
      role="menu"
    >
      {children}
    </div>
  );
}

// ─── FlyoutItem ─────────────────────────────────────────────────────

export function FlyoutItem({
  icon: Icon,
  label,
  description,
  onClick,
}: {
  icon?: typeof Type;
  label: string;
  description?: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className="flex w-full items-center gap-3 px-3 py-2 text-left text-txt-secondary hover:bg-bg-hover hover:text-txt-primary transition-colors duration-fast"
    >
      {Icon && <Icon size={13} className="text-txt-tertiary shrink-0" />}
      <div className="min-w-0">
        <div className="text-xs font-medium">{label}</div>
        {description && (
          <div className="text-[10px] text-txt-muted truncate">
            {description}
          </div>
        )}
      </div>
    </button>
  );
}
