import { Fragment, useEffect } from 'react';
import { X } from 'lucide-react';
import { EDITOR_SHORTCUTS } from '@/lib/editor/shortcuts';

/** Keyboard-shortcut help overlay (Phase 2, PR 10). Toggled with `?`; closes on
 *  Escape or backdrop click. Rendered from the single shortcuts source so it
 *  can't drift from EditorNext's key handler (Phase 3, item 7). */

export function KeyboardHelp({ open, onClose }: { open: boolean; onClose: () => void }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Keyboard shortcuts"
    >
      <div
        className="bg-bg-surface border border-border rounded-xl p-5 w-full max-w-md mx-4 max-h-[80vh] overflow-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-txt-primary">Keyboard shortcuts</h2>
          <button onClick={onClose} className="text-txt-tertiary hover:text-txt-primary" aria-label="Close">
            <X size={16} />
          </button>
        </div>
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-xs items-center">
          {EDITOR_SHORTCUTS.map(({ keys, description }) => (
            <Fragment key={description}>
              <dt>
                <span className="inline-block rounded bg-bg-elevated px-1.5 py-0.5 tabular-nums text-txt-secondary whitespace-nowrap">
                  {keys}
                </span>
              </dt>
              <dd className="text-txt-tertiary">{description}</dd>
            </Fragment>
          ))}
        </dl>
      </div>
    </div>
  );
}
