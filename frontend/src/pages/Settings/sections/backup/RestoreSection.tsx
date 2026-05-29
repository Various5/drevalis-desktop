import { Ref } from 'react';
import { Archive, AlertTriangle, Upload } from 'lucide-react';
import { Trans, useTranslation } from 'react-i18next';
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
  const { t } = useTranslation();
  return (
    <Card className="p-6 border-amber-500/30 bg-amber-500/5">
      <div className="flex items-start gap-3 mb-3">
        <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
        <div>
          <h4 className="font-semibold">{t('settings.backup.restore.heading')}</h4>
          <p className="text-sm text-txt-secondary mt-1">
            <Trans
              i18nKey="settings.backup.restore.warning"
              components={{ 1: <strong /> }}
            />
          </p>
        </div>
      </div>
      <div className="space-y-3 mt-4">
        {/* Path A — pick an archive already in BACKUP_DIRECTORY (no upload). */}
        {archives.length > 0 && (
          <div>
            <label className="block text-xs font-medium text-txt-secondary mb-1">
              {t('settings.backup.restore.pickExistingLabel')}{' '}
              <span className="text-txt-muted font-normal">
                {t('settings.backup.restore.pickExistingNote')}
              </span>
            </label>
            <select
              value={selectedExisting}
              onChange={(e) => onSelectExistingArchive(e.target.value)}
              disabled={restoring}
              className="block w-full text-sm bg-bg-elevated text-txt-primary rounded p-2 border border-bg-hover"
            >
              <option value="">{t('settings.backup.restore.pickExistingPlaceholder')}</option>
              {archives.map((a) => (
                <option key={a.filename} value={a.filename}>
                  {a.filename} · {formatBytes(a.size_bytes)} ·{' '}
                  {new Date(a.created_at).toLocaleString()}
                </option>
              ))}
            </select>
            <p className="mt-1 text-[11px] text-txt-muted leading-relaxed">
              <Trans
                i18nKey="settings.backup.restore.pickExistingHint"
                components={{
                  1: <span className="font-mono" />,
                  2: <span className="font-mono" />,
                }}
              />
            </p>
          </div>
        )}

        <div>
          <label className="block text-xs font-medium text-txt-secondary mb-1">
            {t('settings.backup.restore.uploadLabel')}{' '}
            <span className="text-txt-muted font-normal">{t('settings.backup.restore.uploadNote')}</span>
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
          <div className="text-xs font-medium text-txt-secondary">{t('settings.backup.restore.whatToRestore')}</div>
          <label className="flex items-center gap-2 text-xs text-txt-secondary">
            <input
              type="checkbox"
              checked={restoreDb}
              onChange={(e) => onRestoreDbChange(e.target.checked)}
              className="rounded"
            />
            <span>
              <Trans
                i18nKey="settings.backup.restore.dbLabel"
                components={{ 1: <strong className="text-txt-primary" /> }}
              />
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
              <Trans
                i18nKey="settings.backup.restore.mediaLabel"
                components={{ 1: <strong className="text-txt-primary" /> }}
              />
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
            {t('settings.backup.restore.allowKeyMismatch')}
          </label>
        </div>
        <div>
          <label className="block text-xs font-medium text-txt-secondary mb-1">
            <Trans
              i18nKey="settings.backup.restore.confirmLabel"
              components={{ 1: <strong className="text-txt-primary font-mono" /> }}
            />
          </label>
          <Input
            value={restoreConfirm}
            onChange={(e) => onRestoreConfirmChange(e.target.value)}
            placeholder={t('settings.backup.restore.confirmPlaceholder')}
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
            {restoring && selectedExisting
              ? t('settings.backup.restore.restoringEllipsis')
              : t('settings.backup.restore.restoreFromPicked')}
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
            {restoring && !selectedExisting
              ? t('settings.backup.restore.restoringEllipsis')
              : t('settings.backup.restore.uploadAndRestore')}
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
                {t('settings.backup.restore.stageLabel')}{' '}
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
                    {t('settings.backup.restore.dismiss')}
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
                <Trans
                  i18nKey="settings.backup.restore.uploadingNoLeave"
                  components={{ 1: <strong /> }}
                />
              </div>
            ) : (
              <div className="mt-1 text-[11px] text-txt-muted">
                {t('settings.backup.restore.safeToLeave')}
              </div>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}
