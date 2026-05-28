import { useState } from 'react';
import { AlertTriangle, Database, Download, FileArchive, Trash2, UserX } from 'lucide-react';
import { Trans, useTranslation } from 'react-i18next';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { useToast } from '@/components/ui/Toast';
import { ConfirmDangerousDialog } from '@/components/ui/ConfirmDangerousDialog';
import { danger, formatError } from '@/lib/api';
import { useAuth } from '@/lib/useAuth';

/**
 * DiagnosticsSection — lets an owner download a redacted diagnostics bundle
 * to send to support. The ZIP contains configuration (secrets redacted),
 * health status, recent logs, system info, and the current DB revision.
 */
export function DiagnosticsSection() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const { user } = useAuth();
  const [downloading, setDownloading] = useState(false);
  // Phase 4 typed-confirm danger zone — one dialog state per action so an
  // open Reset dialog can't be smashed by an accidental click on Wipe.
  const [wipeOpen, setWipeOpen] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [busy, setBusy] = useState<'wipe' | 'reset' | 'delete' | null>(null);
  const isOwner = user?.role === 'owner';

  const onWipeStorage = async () => {
    setBusy('wipe');
    try {
      const { files_removed, bytes_freed } = await danger.wipeStorage();
      const mb = (bytes_freed / (1024 * 1024)).toFixed(1);
      toast.success(t('settings.diagnostics.wipe.toastSuccess'), {
        description: t('settings.diagnostics.wipe.toastSuccessDesc', { count: files_removed, mb }),
      });
      setWipeOpen(false);
    } catch (err) {
      toast.error(t('settings.diagnostics.wipe.toastFailed'), { description: formatError(err) });
    } finally {
      setBusy(null);
    }
  };

  const onResetDatabase = async () => {
    setBusy('reset');
    try {
      const { truncated } = await danger.resetDatabase();
      toast.success(t('settings.diagnostics.reset.toastSuccess'), {
        description: t('settings.diagnostics.reset.toastSuccessDesc', { count: truncated.length }),
      });
      setResetOpen(false);
      // Hard reload so every cached query starts from a clean DB.
      setTimeout(() => window.location.reload(), 800);
    } catch (err) {
      toast.error(t('settings.diagnostics.reset.toastFailed'), { description: formatError(err) });
    } finally {
      setBusy(null);
    }
  };

  const onDeleteAccount = async () => {
    setBusy('delete');
    try {
      await danger.deleteAccount();
      // Cookie was cleared on the server; bounce to /login to clear local state.
      window.location.href = '/login';
    } catch (err) {
      toast.error(t('settings.diagnostics.delete.toastFailed'), { description: formatError(err) });
      setBusy(null);
    }
  };

  const onDownload = async () => {
    setDownloading(true);
    try {
      const res = await fetch('/api/v1/diagnostics/bundle');
      if (!res.ok) {
        const text = await res.text().catch(() => res.statusText);
        throw new Error(`${res.status}: ${text}`);
      }

      const blob = await res.blob();
      const dateStr = new Date().toISOString().slice(0, 10); // YYYY-MM-DD
      const filename = `drevalis-diagnostics-${dateStr}.zip`;

      const url = URL.createObjectURL(blob);
      try {
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = filename;
        anchor.style.display = 'none';
        document.body.appendChild(anchor);
        anchor.click();
        document.body.removeChild(anchor);
      } finally {
        // Revoke after a short delay so the download starts before the
        // object URL is released.
        setTimeout(() => URL.revokeObjectURL(url), 10_000);
      }

      toast.success(t('settings.diagnostics.downloadSuccess'), {
        description: filename,
      });
    } catch (err) {
      toast.error(t('settings.diagnostics.downloadFailed'), { description: formatError(err) });
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="space-y-6">
      <Card className="p-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="font-semibold text-lg flex items-center gap-2 mb-1">
              <FileArchive className="w-5 h-5" />
              {t('settings.diagnostics.title')}
            </h3>
            <p className="text-sm text-txt-secondary">{t('settings.diagnostics.intro')}</p>
            <ul className="mt-3 space-y-1 text-xs text-txt-muted list-disc list-inside">
              <li>
                <code>config.json</code> — {t('settings.diagnostics.bundle.configPrefix')}{' '}
                <code>***REDACTED***</code>
              </li>
              <li>
                <code>health.json</code> — {t('settings.diagnostics.bundle.health')}
              </li>
              <li>
                <code>recent_logs.txt</code> — {t('settings.diagnostics.bundle.logs')}
              </li>
              <li>
                <code>system.json</code> — {t('settings.diagnostics.bundle.system')}
              </li>
              <li>
                <code>db_revision.txt</code> — {t('settings.diagnostics.bundle.dbRevision')}
              </li>
            </ul>
          </div>
          <Button
            onClick={onDownload}
            disabled={downloading}
            variant="primary"
            className="shrink-0"
          >
            <Download className="w-4 h-4 mr-1.5" />
            {downloading ? t('settings.diagnostics.preparing') : t('settings.diagnostics.download')}
          </Button>
        </div>
      </Card>

      {/* ── Danger zone (Phase 4) ─────────────────────────────────────── */}
      <Card className="p-6 border-error/30">
        <h3 className="font-semibold text-lg flex items-center gap-2 mb-1 text-error">
          <AlertTriangle className="w-5 h-5" />
          {t('settings.diagnostics.dangerZone.title')}
        </h3>
        <p className="text-sm text-txt-secondary mb-5">{t('settings.diagnostics.dangerZone.intro')}</p>

        <div className="divide-y divide-border">
          {/* Wipe storage */}
          <div className="flex items-start justify-between gap-4 py-4">
            <div className="flex items-start gap-3 min-w-0">
              <Trash2 size={18} className="text-error mt-0.5 shrink-0" />
              <div className="min-w-0">
                <p className="text-sm font-semibold text-txt-primary">
                  {t('settings.diagnostics.wipe.label')}
                </p>
                <p className="text-xs text-txt-secondary mt-1">
                  <Trans
                    i18nKey="settings.diagnostics.wipe.description"
                    components={{ 1: <em /> }}
                  />
                </p>
              </div>
            </div>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => setWipeOpen(true)}
              className="shrink-0"
            >
              {t('settings.diagnostics.wipe.button')}
            </Button>
          </div>

          {/* Reset database */}
          <div className="flex items-start justify-between gap-4 py-4">
            <div className="flex items-start gap-3 min-w-0">
              <Database size={18} className="text-error mt-0.5 shrink-0" />
              <div className="min-w-0">
                <p className="text-sm font-semibold text-txt-primary">
                  {t('settings.diagnostics.reset.label')}
                </p>
                <p className="text-xs text-txt-secondary mt-1">
                  {t('settings.diagnostics.reset.description')}
                </p>
              </div>
            </div>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => setResetOpen(true)}
              className="shrink-0"
            >
              {t('settings.diagnostics.reset.button')}
            </Button>
          </div>

          {/* Delete account */}
          <div className="flex items-start justify-between gap-4 py-4">
            <div className="flex items-start gap-3 min-w-0">
              <UserX size={18} className="text-error mt-0.5 shrink-0" />
              <div className="min-w-0">
                <p className="text-sm font-semibold text-txt-primary">
                  {t('settings.diagnostics.delete.label')}
                </p>
                <p className="text-xs text-txt-secondary mt-1">
                  {isOwner
                    ? t('settings.diagnostics.delete.descriptionOwner')
                    : t('settings.diagnostics.delete.description')}
                </p>
              </div>
            </div>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => setDeleteOpen(true)}
              disabled={isOwner}
              className="shrink-0"
            >
              {t('settings.diagnostics.delete.button')}
            </Button>
          </div>
        </div>
      </Card>

      {/* Confirm words (WIPE / RESET / DELETE) stay in English on purpose —
          they're action codes the user types to gate the operation, not
          prose. The dialog primitive itself still hardcodes "Type X to
          confirm" in English; that lives in ConfirmDangerousDialog and is a
          separate i18n task. ``returnObjects: true`` returns the
          ``consequences`` arrays directly from the locale JSON. */}
      <ConfirmDangerousDialog
        open={wipeOpen}
        onClose={() => setWipeOpen(false)}
        onConfirm={() => void onWipeStorage()}
        title={t('settings.diagnostics.wipe.dialogTitle')}
        warning={
          <Trans
            i18nKey="settings.diagnostics.wipe.warning"
            components={{ 1: <strong className="text-txt-primary" /> }}
          />
        }
        consequences={
          t('settings.diagnostics.wipe.consequences', { returnObjects: true }) as string[]
        }
        confirmWord="WIPE"
        confirmLabel={t('settings.diagnostics.wipe.confirmLabel')}
        loading={busy === 'wipe'}
      />

      <ConfirmDangerousDialog
        open={resetOpen}
        onClose={() => setResetOpen(false)}
        onConfirm={() => void onResetDatabase()}
        title={t('settings.diagnostics.reset.dialogTitle')}
        warning={
          <Trans
            i18nKey="settings.diagnostics.reset.warning"
            components={{ 1: <strong className="text-txt-primary" /> }}
          />
        }
        consequences={
          t('settings.diagnostics.reset.consequences', { returnObjects: true }) as string[]
        }
        confirmWord="RESET"
        confirmLabel={t('settings.diagnostics.reset.confirmLabel')}
        loading={busy === 'reset'}
      />

      <ConfirmDangerousDialog
        open={deleteOpen}
        onClose={() => setDeleteOpen(false)}
        onConfirm={() => void onDeleteAccount()}
        title={t('settings.diagnostics.delete.dialogTitle')}
        warning={
          <Trans
            i18nKey="settings.diagnostics.delete.warning"
            values={{ email: user?.email ?? t('settings.diagnostics.delete.thisAccount') }}
            components={{
              1: <strong className="text-txt-primary" />,
              2: <strong className="text-txt-primary" />,
            }}
          />
        }
        consequences={
          t('settings.diagnostics.delete.consequences', { returnObjects: true }) as string[]
        }
        confirmWord="DELETE"
        confirmLabel={t('settings.diagnostics.delete.confirmLabel')}
        loading={busy === 'delete'}
      />
    </div>
  );
}
