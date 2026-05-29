import { useEffect, useState } from 'react';
import { Calendar } from 'lucide-react';
import { Trans, useTranslation } from 'react-i18next';
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
  const { t } = useTranslation();
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
          ? t('settings.backup.schedule.enabledToast')
          : t('settings.backup.schedule.disabledToast'),
      );
    } catch (err) {
      toast.error(t('settings.backup.schedule.saveFailed'), { description: formatError(err) });
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
            {t('settings.backup.schedule.title')}
          </h3>
          <p className="text-xs text-txt-secondary mt-1">
            {t('settings.backup.schedule.intro')}
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
              {t('settings.backup.schedule.toggleLabel')}
            </div>
            <div className="text-[11px] text-txt-tertiary mt-0.5">
              {autoEnabled
                ? t('settings.backup.schedule.forcedByEnv')
                : effective
                  ? t('settings.backup.schedule.savingUpTo', { count: retention })
                  : t('settings.backup.schedule.willKeep', { count: retention })}
            </div>
          </div>
        </label>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
        <div className="rounded bg-bg-elevated p-3">
          <div className="text-txt-muted uppercase tracking-wider mb-1">{t('settings.backup.schedule.directoryLabel')}</div>
          <div className="text-txt-primary font-mono break-all">
            {backupDirectoryAbs || backupDirectory}
          </div>
          {backupDirectoryHostSource && backupDirectoryHostSource !== backupDirectoryAbs && (
            <>
              <div className="text-txt-muted uppercase tracking-wider mt-3 mb-1">
                {t('settings.backup.schedule.mountSourceLabel')}
              </div>
              <div className="text-accent font-mono break-all">
                {backupDirectoryHostSource}
              </div>
            </>
          )}
        </div>
        <div className="rounded bg-bg-elevated p-3">
          <div className="text-txt-muted uppercase tracking-wider mb-1">{t('settings.backup.schedule.retentionLabel')}</div>
          <div className="text-txt-primary">
            {t('settings.backup.schedule.retentionValue', { count: retention })}
          </div>
          <div className="text-[11px] text-txt-tertiary mt-1">
            <Trans i18nKey="settings.backup.schedule.retentionEnvHint" components={{ 1: <code /> }} />
          </div>
        </div>
        <div className="rounded bg-bg-elevated p-3">
          <div className="text-txt-muted uppercase tracking-wider mb-1">{t('settings.backup.schedule.statusLabel')}</div>
          <div className={effective ? 'text-accent' : 'text-txt-secondary'}>
            {effective ? t('settings.backup.schedule.statusActive') : t('settings.backup.schedule.statusDisabled')}
          </div>
          <div className="text-[11px] text-txt-tertiary mt-1">
            {effective
              ? t('settings.backup.schedule.statusActiveHint')
              : t('settings.backup.schedule.statusDisabledHint')}
          </div>
        </div>
      </div>

      <p className="text-[11px] text-txt-tertiary leading-relaxed">
        <Trans
          i18nKey="settings.backup.schedule.offBoxHint"
          components={{ 1: <code className="text-txt-secondary" /> }}
        />
      </p>

      {userToggle === null && (
        <Button variant="ghost" size="sm" onClick={() => window.location.reload()}>
          {t('settings.backup.schedule.reload')}
        </Button>
      )}
    </Card>
  );
}
