import { useEffect } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';

// ---------------------------------------------------------------------------
// App-wide keyboard shortcut cheat sheet
// ---------------------------------------------------------------------------
//
// Toggled via ``?`` from anywhere in the app shell (Layout owns the
// keystroke). The Episode Editor has its own context-specific overlay
// — Layout suppresses the global ``?`` while on that route so the two
// overlays don't fight.

interface ShortcutOverlayProps {
  open: boolean;
  onClose: () => void;
}

interface ShortcutEntry {
  keys: string[];
  description: string;
}

interface ShortcutGroup {
  title: string;
  entries: ShortcutEntry[];
}

const GROUPS: readonly ShortcutGroup[] = [
  {
    title: 'Global',
    entries: [
      { keys: ['Ctrl', 'K'], description: 'Open command palette' },
      { keys: ['?'], description: 'Show this overlay' },
      { keys: ['Esc'], description: 'Close current dialog or overlay' },
    ],
  },
  {
    title: 'Lists',
    entries: [
      { keys: ['↑'], description: 'Previous item' },
      { keys: ['↓'], description: 'Next item' },
      { keys: ['Enter'], description: 'Open selected item' },
    ],
  },
  {
    title: 'Editor',
    entries: [
      { keys: ['Space'], description: 'Play / pause' },
      { keys: ['S'], description: 'Split clip at playhead' },
      { keys: ['⌫'], description: 'Delete selected clip' },
      { keys: ['Ctrl', 'Z'], description: 'Undo' },
      { keys: ['Ctrl', 'Shift', 'Z'], description: 'Redo' },
      { keys: ['←', '→'], description: 'Nudge playhead 0.1s (Shift = 1s)' },
      { keys: ['Home', 'End'], description: 'Jump to start / end' },
    ],
  },
];

function Kbd({ label }: { label: string }) {
  return (
    <kbd className="inline-flex items-center justify-center min-w-[24px] h-6 px-1.5 rounded border border-white/10 bg-white/[0.04] text-[11px] font-mono text-txt-secondary">
      {label}
    </kbd>
  );
}

function ShortcutOverlay({ open, onClose }: ShortcutOverlayProps) {
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onClose]);

  if (!open) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-[9998] flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Keyboard shortcuts"
    >
      <div
        className="bg-bg-elevated border border-white/[0.06] rounded-xl shadow-xl max-w-2xl w-[92%] max-h-[80vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between p-5 border-b border-white/[0.06]">
          <h2 className="font-display text-lg font-semibold">Keyboard shortcuts</h2>
          <button
            onClick={onClose}
            className="text-txt-tertiary hover:text-txt-primary p-1 rounded"
            aria-label="Close shortcuts overlay"
          >
            <X size={18} />
          </button>
        </div>
        <div className="p-5 grid gap-6 sm:grid-cols-2">
          {GROUPS.map((group) => (
            <div key={group.title}>
              <h3 className="text-[11px] font-display font-bold uppercase tracking-[0.15em] text-txt-tertiary mb-3">
                {group.title}
              </h3>
              <dl className="space-y-2">
                {group.entries.map((entry) => (
                  <div
                    key={entry.description}
                    className="flex items-center justify-between gap-3 text-xs"
                  >
                    <dt className="flex items-center gap-1 shrink-0">
                      {entry.keys.map((k, i) => (
                        <span key={`${entry.description}-${k}-${i}`} className="flex items-center gap-1">
                          {i > 0 && <span className="text-txt-tertiary">+</span>}
                          <Kbd label={k} />
                        </span>
                      ))}
                    </dt>
                    <dd className="text-txt-secondary text-right">{entry.description}</dd>
                  </div>
                ))}
              </dl>
            </div>
          ))}
        </div>
        <p className="px-5 pb-5 text-[11px] text-txt-tertiary">
          The Episode Editor has its own context-specific overlay — also bound to <kbd className="kbd">?</kbd>.
        </p>
      </div>
    </div>,
    document.body,
  );
}

export { ShortcutOverlay };
