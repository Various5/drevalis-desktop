import { type ReactNode, useEffect, useState } from 'react';
import { AlertTriangle } from 'lucide-react';
import { Dialog, DialogFooter } from './Dialog';
import { Button } from './Button';
import { Input } from './Input';

/**
 * Cloudflare-style destructive confirmation (Phase 4). Shows a warning + the
 * consequences, and gates the action behind typing an exact confirm word
 * (e.g. "DELETE", "EXPOSE", or the resource name) — so an irreversible /
 * dangerous action can't be triggered by a stray click. Reused by the LAN
 * exposure toggle and every destructive action (delete series, reset db, …).
 */

export function ConfirmDangerousDialog({
  open,
  onClose,
  onConfirm,
  title,
  warning,
  confirmWord,
  confirmLabel = 'Confirm',
  consequences,
  loading = false,
}: {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  /** One-paragraph explanation of what's about to happen (the threat model). */
  warning: ReactNode;
  /** The exact text the user must type to enable the confirm button. */
  confirmWord: string;
  confirmLabel?: string;
  /** Optional bullet list of concrete consequences. */
  consequences?: string[];
  loading?: boolean;
}) {
  const [typed, setTyped] = useState('');
  useEffect(() => {
    if (open) setTyped('');
  }, [open]);

  const matches = typed.trim() === confirmWord;

  return (
    <Dialog open={open} onClose={onClose} title={title} maxWidth="sm">
      <div className="space-y-3 text-sm">
        <div className="flex gap-2 rounded-md border border-error/40 bg-error/5 p-3">
          <AlertTriangle size={16} className="text-error shrink-0 mt-0.5" aria-hidden="true" />
          <div className="text-txt-secondary leading-snug">{warning}</div>
        </div>

        {consequences && consequences.length > 0 && (
          <ul className="list-disc pl-5 text-xs text-txt-tertiary space-y-1">
            {consequences.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        )}

        <div>
          <label className="block text-xs text-txt-tertiary mb-1">
            Type{' '}
            <span className="font-mono font-semibold text-txt-primary select-none">{confirmWord}</span>{' '}
            to confirm
          </label>
          <Input
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            placeholder={confirmWord}
            autoFocus
            autoComplete="off"
            aria-label={`Type ${confirmWord} to confirm`}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && matches && !loading) onConfirm();
            }}
          />
        </div>
      </div>

      <DialogFooter>
        <Button variant="ghost" onClick={onClose} disabled={loading}>
          Cancel
        </Button>
        <Button variant="destructive" onClick={onConfirm} disabled={!matches || loading} loading={loading}>
          {confirmLabel}
        </Button>
      </DialogFooter>
    </Dialog>
  );
}
