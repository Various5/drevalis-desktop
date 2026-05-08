import type { CalendarView } from './types';

// ---------------------------------------------------------------------------
// ViewModeToggle — Day / Week / Month segmented control
// ---------------------------------------------------------------------------

interface ViewModeToggleProps {
  view: CalendarView;
  onChange: (view: CalendarView) => void;
}

const MODES: { value: CalendarView; label: string }[] = [
  { value: 'day', label: 'Day' },
  { value: 'week', label: 'Week' },
  { value: 'month', label: 'Month' },
];

export function ViewModeToggle({ view, onChange }: ViewModeToggleProps) {
  return (
    <div
      role="group"
      aria-label="Calendar view mode"
      className="inline-flex rounded-md border border-border p-0.5 bg-bg-elevated"
    >
      {MODES.map(({ value, label }) => (
        <button
          key={value}
          type="button"
          role="radio"
          aria-checked={view === value}
          onClick={() => onChange(value)}
          className={[
            'text-xs px-2.5 py-1 rounded font-medium transition-colors',
            view === value
              ? 'bg-accent/15 text-accent'
              : 'text-txt-secondary hover:text-txt-primary',
          ].join(' ')}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
