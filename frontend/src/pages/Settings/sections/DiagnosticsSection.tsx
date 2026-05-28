import { useState } from 'react';
import { AlertTriangle, Database, Download, FileArchive, Trash2, UserX } from 'lucide-react';
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
      toast.success('Storage wiped', {
        description: `${files_removed} files removed, ${mb} MB freed.`,
      });
      setWipeOpen(false);
    } catch (err) {
      toast.error('Wipe failed', { description: formatError(err) });
    } finally {
      setBusy(null);
    }
  };

  const onResetDatabase = async () => {
    setBusy('reset');
    try {
      const { truncated } = await danger.resetDatabase();
      toast.success('Database reset', {
        description: `${truncated.length} tables cleared. You're still signed in.`,
      });
      setResetOpen(false);
      // Hard reload so every cached query starts from a clean DB.
      setTimeout(() => window.location.reload(), 800);
    } catch (err) {
      toast.error('Reset failed', { description: formatError(err) });
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
      toast.error('Delete failed', { description: formatError(err) });
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

      toast.success('Diagnostics bundle downloaded', {
        description: filename,
      });
    } catch (err) {
      toast.error('Download failed', { description: formatError(err) });
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
              Support Diagnostics
            </h3>
            <p className="text-sm text-txt-secondary">
              Download a ZIP bundle to send to support when reporting an issue. The
              bundle contains redacted configuration, health status, recent logs,
              system info, and the current database revision.
            </p>
            <ul className="mt-3 space-y-1 text-xs text-txt-muted list-disc list-inside">
              <li>
                <code>config.json</code> — all settings with secrets replaced by{' '}
                <code>***REDACTED***</code>
              </li>
              <li>
                <code>health.json</code> — database, FFmpeg, and Piper status
              </li>
              <li>
                <code>recent_logs.txt</code> — last 1000 log lines (if a log file is
                configured)
              </li>
              <li>
                <code>system.json</code> — Python version, platform, disk space
              </li>
              <li>
                <code>db_revision.txt</code> — current Alembic migration head
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
            {downloading ? 'Preparing...' : 'Download diagnostics'}
          </Button>
        </div>
      </Card>

      {/* ── Danger zone (Phase 4) ─────────────────────────────────────── */}
      <Card className="p-6 border-error/30">
        <h3 className="font-semibold text-lg flex items-center gap-2 mb-1 text-error">
          <AlertTriangle className="w-5 h-5" />
          Danger zone
        </h3>
        <p className="text-sm text-txt-secondary mb-5">
          These actions can&rsquo;t be undone. Always take a backup first
          (Settings &rarr; Backup &rarr; Create backup).
        </p>

        <div className="divide-y divide-border">
          {/* Wipe storage */}
          <div className="flex items-start justify-between gap-4 py-4">
            <div className="flex items-start gap-3 min-w-0">
              <Trash2 size={18} className="text-error mt-0.5 shrink-0" />
              <div className="min-w-0">
                <p className="text-sm font-semibold text-txt-primary">Wipe storage</p>
                <p className="text-xs text-txt-secondary mt-1">
                  Deletes every generated file (voice clips, scenes, renders, thumbnails,
                  intermediate caches) from the storage directory. Database rows that
                  reference those files are left untouched &mdash; use{' '}
                  <em>Reset database</em> for a coordinated wipe of both.
                </p>
              </div>
            </div>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => setWipeOpen(true)}
              className="shrink-0"
            >
              Wipe&hellip;
            </Button>
          </div>

          {/* Reset database */}
          <div className="flex items-start justify-between gap-4 py-4">
            <div className="flex items-start gap-3 min-w-0">
              <Database size={18} className="text-error mt-0.5 shrink-0" />
              <div className="min-w-0">
                <p className="text-sm font-semibold text-txt-primary">Reset database</p>
                <p className="text-xs text-txt-secondary mt-1">
                  Truncates every user-data table (episodes, series, jobs, scheduled
                  posts, integrations, API keys, voice/LLM/ComfyUI configs). You stay
                  signed in &mdash; auth, license, and migration tracking are preserved.
                </p>
              </div>
            </div>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => setResetOpen(true)}
              className="shrink-0"
            >
              Reset&hellip;
            </Button>
          </div>

          {/* Delete account */}
          <div className="flex items-start justify-between gap-4 py-4">
            <div className="flex items-start gap-3 min-w-0">
              <UserX size={18} className="text-error mt-0.5 shrink-0" />
              <div className="min-w-0">
                <p className="text-sm font-semibold text-txt-primary">Delete account</p>
                <p className="text-xs text-txt-secondary mt-1">
                  {isOwner
                    ? 'Owner accounts can’t be deleted from this device — the install would be unrecoverable. Use Reset database to clear content instead.'
                    : 'Permanently deletes this user account from the install and signs you out. Content you authored stays under its original owner.'}
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
              Delete&hellip;
            </Button>
          </div>
        </div>
      </Card>

      <ConfirmDangerousDialog
        open={wipeOpen}
        onClose={() => setWipeOpen(false)}
        onConfirm={() => void onWipeStorage()}
        title="Wipe storage?"
        warning={
          <>
            This permanently deletes every generated file under the storage
            directory. <strong className="text-txt-primary">There is no undo</strong>
            &mdash; restore from a backup if you change your mind.
          </>
        }
        consequences={[
          'All voice clips, scenes, renders, thumbnails, and caches are deleted',
          'Database rows referencing those files remain (broken thumbnails until re-rendered)',
          'Re-generation cost is incurred for anything you want back',
        ]}
        confirmWord="WIPE"
        confirmLabel="Wipe storage"
        loading={busy === 'wipe'}
      />

      <ConfirmDangerousDialog
        open={resetOpen}
        onClose={() => setResetOpen(false)}
        onConfirm={() => void onResetDatabase()}
        title="Reset database?"
        warning={
          <>
            This truncates every user-data table. You stay signed in, but every
            episode, series, scheduled post, and saved configuration is gone.
            <strong className="text-txt-primary"> There is no undo</strong> &mdash;
            restore from a backup if you change your mind.
          </>
        }
        consequences={[
          'All episodes, series, generation jobs, and scheduled posts are removed',
          'All saved API keys, voice profiles, LLM configs, ComfyUI servers are deleted',
          'All connected social platforms are forgotten (you’ll need to reconnect)',
          'The page reloads so cached queries don’t resurrect anything',
        ]}
        confirmWord="RESET"
        confirmLabel="Reset database"
        loading={busy === 'reset'}
      />

      <ConfirmDangerousDialog
        open={deleteOpen}
        onClose={() => setDeleteOpen(false)}
        onConfirm={() => void onDeleteAccount()}
        title="Delete account?"
        warning={
          <>
            This permanently deletes{' '}
            <strong className="text-txt-primary">{user?.email ?? 'this account'}</strong>{' '}
            from the install and signs you out.
            <strong className="text-txt-primary"> There is no undo.</strong>
          </>
        }
        consequences={[
          'You are signed out immediately',
          'Future sign-ins for this email will fail until the account is re-created',
          'Content authored by this user stays in the install (no cascade)',
        ]}
        confirmWord="DELETE"
        confirmLabel="Delete account"
        loading={busy === 'delete'}
      />
    </div>
  );
}
