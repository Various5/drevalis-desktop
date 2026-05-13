import { useEffect, useState } from 'react';
import { Calendar } from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { useToast } from '@/components/ui/Toast';
import { formatError } from '@/lib/api';
import type { BackupListResponse } from './types';

interface ScheduleSectionProps {
  backupDirectoryAbs: BackupListResponse['backup_directory_abs'];
  backupDirectory: BackupListResponse['backup_directory'];
  backupDirectoryHostSource: BackupListResponse['backup_directory_host_source'];
  retention: BackupListResponse['retention'];
  autoEnabled: BackupListResponse['auto_enabled'];
}

// ---------------------------------------------------------------------------
// ScheduleSection — backup auto-run config on the desktop.
// ---------------------------------------------------------------------------
//
// Effective state = ``Settings.backup_auto_enabled`` (env) OR
// ``user.preferences.backup_auto_enabled`` (UI toggle, persisted via
// ``/auth/preferences``). The worker's scheduled_backup job consults
// both at every cron tick, so flipping the toggle here takes effect
// at the next 03:00 UTC tick without a restart.

export function ScheduleSection({
  backupDirectoryAbs,
  backupDirectory,
  backupDirectoryHostSource,
  retention,
  autoEnabled,
}: ScheduleSectionProps) {
  const { toast } = useToast();
  const [userToggle, setUserToggle] = useState<boolean | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const res = await fetch('/api/v1/auth/preferences', { credentials: 'include' });
        if (!res.ok) {
          if (!cancelled) setUserToggle(false);
          return;
        }
        const prefs = (await res.json()) as { backup_auto_enabled?: boolean };
        if (!cancelled) setUserToggle(Boolean(prefs.backup_auto_enabled));
      } catch {
        if (!cancelled) setUserToggle(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const effective = autoEnabled || Boolean(userToggle);

  const toggle = async (next: boolean) => {
    setSaving(true);
    try {
      const res = await fetch('/api/v1/auth/preferences', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ backup_auto_enabled: next || null }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setUserToggle(next);
      toast.success(
        next
          ? 'Auto-backup enabled — next run at 03:00 UTC'
          : 'Auto-backup disabled',
      );
    } catch (err) {
      toast.error('Could not save preference', { description: formatError(err) });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card className="p-6 space-y-5">
      <header className="flex items-start gap-3">
        <Calendar className="w-5 h-5 text-accent shrink-0 mt-0.5" />
        <div>
          <h3 className="text-base font-display font-semibold text-txt-primary">
            Auto-backup schedule
          </h3>
          <p className="text-xs text-txt-secondary mt-1">
            When enabled, the worker creates a backup tarball every day at
            03:00 UTC and prunes archives beyond the retention count.
            Toggle here takes effect at the next tick — no restart needed.
          </p>
        </div>
      </header>

      <div className="rounded-md border border-white/[0.08] bg-bg-elevated/40 p-4">
        <label className="flex items-start gap-3 cursor-pointer">
          <input
            type="checkbox"
            className="w-4 h-4 rounded accent-accent mt-0.5"
            checked={effective}
            // ``autoEnabled`` from env can't be flipped from the UI —
            // restart the app without the env var to disable.
            disabled={autoEnabled || userToggle === null || saving}
            onChange={(e) => void toggle(e.target.checked)}
          />
          <div className="flex-1">
            <div className="text-sm font-medium text-txt-primary">
              Nightly backup at 03:00 UTC
            </div>
            <div className="text-[11px] text-txt-tertiary mt-0.5">
              {autoEnabled
                ? 'Forced on by DREVALIS_BACKUP_AUTO_ENABLED env var. Unset the env to disable.'
                : effective
                  ? `Saving up to ${retention} archive${retention === 1 ? '' : 's'}; older ones are deleted.`
                  : `When you turn this on the worker keeps the last ${retention} archive${retention === 1 ? '' : 's'}.`}
            </div>
          </div>
        </label>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
        <div className="rounded bg-bg-elevated p-3">
          <div className="text-txt-muted uppercase tracking-wider mb-1">Directory</div>
          <div className="text-txt-primary font-mono break-all">
            {backupDirectoryAbs || backupDirectory}
          </div>
          {backupDirectoryHostSource && backupDirectoryHostSource !== backupDirectoryAbs && (
            <>
              <div className="text-txt-muted uppercase tracking-wider mt-3 mb-1">
                Mount source
              </div>
              <div className="text-accent font-mono break-all">
                {backupDirectoryHostSource}
              </div>
            </>
          )}
        </div>
        <div className="rounded bg-bg-elevated p-3">
          <div className="text-txt-muted uppercase tracking-wider mb-1">Retention</div>
          <div className="text-txt-primary">
            Keep {retention} most recent
          </div>
          <div className="text-[11px] text-txt-tertiary mt-1">
            Set <code>DREVALIS_BACKUP_RETENTION</code> to change.
          </div>
        </div>
        <div className="rounded bg-bg-elevated p-3">
          <div className="text-txt-muted uppercase tracking-wider mb-1">Status</div>
          <div className={effective ? 'text-accent' : 'text-txt-secondary'}>
            {effective ? 'Nightly at 03:00 UTC' : 'Disabled'}
          </div>
          <div className="text-[11px] text-txt-tertiary mt-1">
            {effective
              ? 'Toggle off above to pause.'
              : 'Manual backups still work — use the button below.'}
          </div>
        </div>
      </div>

      <p className="text-[11px] text-txt-tertiary leading-relaxed">
        Want backups off-box? Point{' '}
        <code className="text-txt-secondary">DREVALIS_BACKUP_DIRECTORY</code> at a
        synced folder (Dropbox, OneDrive, Syncthing, an SMB/NFS mount) and the
        nightly archive lands there automatically.
      </p>

      {userToggle === null && (
        <Button variant="ghost" size="sm" onClick={() => window.location.reload()}>
          Reload
        </Button>
      )}
    </Card>
  );
}
