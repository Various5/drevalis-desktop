import { Ref } from 'react';
import { Archive, AlertTriangle, Upload } from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import type { BackupArchive, RestoreProgress } from './types';
import { formatBytes } from './utils';

interface RestoreSectionProps {
  archives: BackupArchive[];
  restoring: boolean;
  restoreProgress: RestoreProgress | null;
  selectedExisting: string;
  restoreConfirm: string;
  allowKeyMismatch: boolean;
  restoreDb: boolean;
  restoreMedia: boolean;
  // React.Ref<HTMLInputElement> accepts RefObject<HTMLInputElement | null>
  // from the parent's useRef without requiring non-null assertions.
  fileInputRef: Ref<HTMLInputElement>;
  onRestoreConfirmChange: (value: string) => void;
  onAllowKeyMismatchChange: (value: boolean) => void;
  onRestoreDbChange: (value: boolean) => void;
  onRestoreMediaChange: (value: boolean) => void;
  onRestoreFromExisting: () => void;
  onRestore: () => void;
  onDismissProgress: () => void;
  // Parent-side handlers that need to access fileInputRef.current:
  // selecting an existing archive clears the file picker (and vice versa).
  onSelectExistingArchive: (filename: string) => void;
  onFileInputChange: () => void;
}

export function RestoreSection({
  archives,
  restoring,
  restoreProgress,
  selectedExisting,
  restoreConfirm,
  allowKeyMismatch,
  restoreDb,
  restoreMedia,
  fileInputRef,
  onRestoreConfirmChange,
  onAllowKeyMismatchChange,
  onRestoreDbChange,
  onRestoreMediaChange,
  onRestoreFromExisting,
  onRestore,
  onDismissProgress,
  onSelectExistingArchive,
  onFileInputChange,
}: RestoreSectionProps) {
  return (
    <Card className="p-6 border-amber-500/30 bg-amber-500/5">
      <div className="flex items-start gap-3 mb-3">
        <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
        <div>
          <h4 className="font-semibold">Restore from archive</h4>
          <p className="text-sm text-txt-secondary mt-1">
            <strong>Destructive.</strong> Restoring truncates every user table and overwrites
            storage files with the contents of the archive. Your current content is deleted. This
            is the right action when migrating to a new machine.
          </p>
        </div>
      </div>
      <div className="space-y-3 mt-4">
        {/* Path A — pick an archive already in BACKUP_DIRECTORY (no upload). */}
        {archives.length > 0 && (
          <div>
            <label className="block text-xs font-medium text-txt-secondary mb-1">
              1a. Pick an archive already on disk{' '}
              <span className="text-txt-muted font-normal">
                (recommended for archives &gt;5 GB)
              </span>
            </label>
            <select
              value={selectedExisting}
              onChange={(e) => onSelectExistingArchive(e.target.value)}
              disabled={restoring}
              className="block w-full text-sm bg-bg-elevated text-txt-primary rounded p-2 border border-bg-hover"
            >
              <option value="">— pick an archive —</option>
              {archives.map((a) => (
                <option key={a.filename} value={a.filename}>
                  {a.filename} · {formatBytes(a.size_bytes)} ·{' '}
                  {new Date(a.created_at).toLocaleString()}
                </option>
              ))}
            </select>
            <p className="mt-1 text-[11px] text-txt-muted leading-relaxed">
              Place multi-GB archives directly in{' '}
              <span className="font-mono">BACKUP_DIRECTORY</span> via{' '}
              <span className="font-mono">docker cp</span> or the host bind-mount, then refresh
              the list. This skips the browser upload entirely — no proxy timeouts, no
              navigation issues.
            </p>
          </div>
        )}

        <div>
          <label className="block text-xs font-medium text-txt-secondary mb-1">
            1b. …or upload a new archive (.tar.gz){' '}
            <span className="text-txt-muted font-normal">(only safe for &lt;5 GB)</span>
          </label>
          <input
            ref={fileInputRef}
            type="file"
            accept=".tar.gz,application/gzip"
            disabled={restoring}
            onChange={onFileInputChange}
            className="block w-full text-sm text-txt-primary file:mr-4 file:py-2 file:px-4 file:rounded file:border-0 file:bg-bg-elevated file:text-txt-primary hover:file:bg-bg-hover disabled:opacity-50"
          />
        </div>
        <div className="space-y-2">
          <div className="text-xs font-medium text-txt-secondary">What to restore</div>
          <label className="flex items-center gap-2 text-xs text-txt-secondary">
            <input
              type="checkbox"
              checked={restoreDb}
              onChange={(e) => onRestoreDbChange(e.target.checked)}
              className="rounded"
            />
            <span>
              <strong className="text-txt-primary">Database rows</strong> — series, episodes,
              audiobooks, configs, OAuth tokens
            </span>
          </label>
          <label className="flex items-center gap-2 text-xs text-txt-secondary">
            <input
              type="checkbox"
              checked={restoreMedia}
              onChange={(e) => onRestoreMediaChange(e.target.checked)}
              className="rounded"
            />
            <span>
              <strong className="text-txt-primary">Media files</strong> — generated videos,
              audiobook audio, voice previews (can be very large)
            </span>
          </label>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <input
            id="allow-key-mismatch"
            type="checkbox"
            checked={allowKeyMismatch}
            onChange={(e) => onAllowKeyMismatchChange(e.target.checked)}
            className="rounded"
          />
          <label htmlFor="allow-key-mismatch" className="text-txt-secondary">
            Allow different ENCRYPTION_KEY (OAuth tokens + API keys will need to be re-entered)
          </label>
        </div>
        <div>
          <label className="block text-xs font-medium text-txt-secondary mb-1">
            2. Type <strong className="text-txt-primary font-mono">RESTORE</strong> to confirm
          </label>
          <Input
            value={restoreConfirm}
            onChange={(e) => onRestoreConfirmChange(e.target.value)}
            placeholder="RESTORE"
          />
        </div>
        <div className="flex gap-2 flex-wrap">
          <Button
            onClick={onRestoreFromExisting}
            disabled={
              restoring ||
              !selectedExisting ||
              restoreConfirm !== 'RESTORE' ||
              (!restoreDb && !restoreMedia)
            }
            variant="primary"
            className="bg-amber-500 hover:bg-amber-400 text-bg-base"
          >
            <Archive className="w-4 h-4 mr-1" />
            {restoring && selectedExisting ? 'Restoring...' : 'Restore from picked archive'}
          </Button>
          <Button
            onClick={onRestore}
            disabled={
              restoring ||
              restoreConfirm !== 'RESTORE' ||
              (!restoreDb && !restoreMedia)
            }
            variant="primary"
            className="bg-amber-500/80 hover:bg-amber-500 text-bg-base"
          >
            <Upload className="w-4 h-4 mr-1" />
            {restoring && !selectedExisting ? 'Restoring...' : 'Upload + restore'}
          </Button>
        </div>

        {restoreProgress && (
          <div
            className="mt-4 rounded border border-amber-500/30 bg-amber-500/5 p-3"
            role="status"
            aria-live="polite"
          >
            <div className="flex items-center justify-between text-xs text-txt-secondary mb-1">
              <span>
                Stage:{' '}
                <span className="font-mono text-txt-primary">{restoreProgress.stage}</span>
              </span>
              <div className="flex items-center gap-2">
                <span className="font-mono text-txt-primary">
                  {restoreProgress.progress_pct}%
                </span>
                {(restoreProgress.stage === 'done' ||
                  restoreProgress.stage === 'failed' ||
                  restoreProgress.stage === 'resuming') && (
                  <button
                    type="button"
                    onClick={onDismissProgress}
                    className="text-[10px] text-txt-muted hover:text-txt-primary underline"
                  >
                    dismiss
                  </button>
                )}
              </div>
            </div>
            <div
              className="h-2 w-full rounded bg-bg-elevated overflow-hidden"
              role="progressbar"
              aria-valuenow={restoreProgress.progress_pct}
              aria-valuemin={0}
              aria-valuemax={100}
            >
              <div
                className={
                  restoreProgress.stage === 'failed'
                    ? 'h-full bg-red-500 transition-all duration-200'
                    : restoreProgress.stage === 'done'
                      ? 'h-full bg-green-500 transition-all duration-200'
                      : 'h-full bg-amber-500 transition-all duration-200'
                }
                style={{ width: `${restoreProgress.progress_pct}%` }}
              />
            </div>
            <div className="mt-2 text-xs text-txt-secondary">{restoreProgress.message}</div>
            {restoreProgress.stage === 'uploading' ? (
              <div className="mt-1 text-[11px] text-red-400 leading-relaxed">
                <strong>Don't navigate away.</strong> The upload is browser-bound — leaving
                this page aborts it and you'll have to start over. For multi-GB archives,
                cancel and use "Restore from picked archive" instead.
              </div>
            ) : (
              <div className="mt-1 text-[11px] text-txt-muted">
                Safe to navigate away — the restore runs in the background on the worker.
                Come back to this page to see progress.
              </div>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}
