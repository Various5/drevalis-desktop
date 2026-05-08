import { useEffect, useState } from 'react';
import { Check, ChevronDown, Palette } from 'lucide-react';

// Popover picker for the built-in visual style presets. Renders as a
// pill that opens a card grid of preset previews on click. Picking
// one writes the preset's value into the prompt textarea; the user
// can then tweak the wording freely, which is the behavior the UX
// audit said was opaque in the old rail-of-chips layout. A subtle
// accent border marks the currently-active preset so the connection
// between "pick one" and "what's in the text" is visible.

export interface VisualStylePreset {
  label: string;
  value: string;
}

export function VisualStylePresetPopover({
  presets,
  currentValue,
  onPick,
}: {
  presets: readonly VisualStylePreset[];
  currentValue: string;
  onPick: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const activeLabel =
    presets.find((p) => p.value === currentValue)?.label ?? 'Custom';

  useEffect(() => {
    if (!open) return;
    const handler = () => setOpen(false);
    window.addEventListener('click', handler);
    return () => window.removeEventListener('click', handler);
  }, [open]);

  return (
    <div className="relative inline-block">
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        className="inline-flex items-center gap-2 rounded-full border border-border bg-bg-elevated px-3 py-1.5 text-xs font-medium text-txt-secondary hover:text-txt-primary hover:bg-bg-hover transition-colors duration-fast"
        aria-haspopup="dialog"
        aria-expanded={open}
      >
        <Palette size={12} className="text-accent" />
        Style: <span className="text-txt-primary">{activeLabel}</span>
        <ChevronDown
          size={11}
          className={[
            'transition-transform duration-fast',
            open ? 'rotate-180' : '',
          ].join(' ')}
        />
      </button>
      {open && (
        <div
          className="absolute left-0 z-20 mt-2 w-[520px] max-w-[90vw] rounded-lg border border-border bg-bg-surface shadow-xl p-3"
          onClick={(e) => e.stopPropagation()}
          role="dialog"
          aria-label="Visual style presets"
        >
          <div className="mb-2 flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-txt-tertiary">
              Presets
            </span>
            <span className="text-[11px] text-txt-muted">
              {presets.length} options
            </span>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 max-h-[320px] overflow-y-auto">
            {presets.map((preset) => {
              const active = preset.value === currentValue;
              return (
                <button
                  key={preset.label}
                  type="button"
                  onClick={() => {
                    onPick(preset.value);
                    setOpen(false);
                  }}
                  className={[
                    'group rounded-md border p-2.5 text-left transition-colors duration-fast',
                    active
                      ? 'border-accent bg-accent/10'
                      : 'border-border bg-bg-elevated hover:border-accent/40 hover:bg-bg-hover',
                  ].join(' ')}
                  aria-pressed={active}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span
                      className={[
                        'text-xs font-semibold',
                        active ? 'text-accent' : 'text-txt-primary',
                      ].join(' ')}
                    >
                      {preset.label}
                    </span>
                    {active && (
                      <Check size={12} className="text-accent shrink-0" />
                    )}
                  </div>
                  <p className="mt-1 text-[10px] text-txt-muted line-clamp-2">
                    {preset.value}
                  </p>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
