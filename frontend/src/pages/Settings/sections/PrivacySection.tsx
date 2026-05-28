import { useEffect, useState } from 'react';
import { ShieldCheck, AlertTriangle, CheckCircle2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';

type TelemetryStatus = {
  dsn: string | null;
  enabled: boolean;
  environment: string;
  release: string | null;
};

type Preferences = {
  telemetry_opt_out?: boolean;
};

export function PrivacySection() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<TelemetryStatus | null>(null);
  const [optOut, setOptOut] = useState<boolean>(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  async function reload() {
    setLoading(true);
    try {
      const [statusRes, prefsRes] = await Promise.all([
        fetch('/api/v1/telemetry/bootstrap', { credentials: 'include' }),
        fetch('/api/v1/auth/preferences', { credentials: 'include' }),
      ]);
      if (statusRes.ok) setStatus(await statusRes.json());
      if (prefsRes.ok) {
        const prefs: Preferences = await prefsRes.json();
        setOptOut(Boolean(prefs.telemetry_opt_out));
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void reload();
  }, []);

  async function toggleOptOut(next: boolean) {
    setSaving(true);
    try {
      await fetch('/api/v1/auth/preferences', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ telemetry_opt_out: next || null }),
      });
      setOptOut(next);
      // Refresh bootstrap so the displayed "currently sending"
      // pill flips immediately.
      await reload();
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <Card className="p-6">{t('settings.privacy.loading')}</Card>;

  const dsnConfigured = Boolean(status?.dsn) || Boolean(status?.environment);
  const currentlySending = Boolean(status?.enabled) && Boolean(status?.dsn);

  return (
    <Card className="p-6 space-y-6">
      <header className="flex items-start gap-3">
        <ShieldCheck className="w-6 h-6 text-accent flex-shrink-0 mt-0.5" />
        <div>
          <h2 className="text-lg font-semibold">{t('settings.privacy.title')}</h2>
          <p className="text-sm text-muted-foreground mt-1">{t('settings.privacy.intro')}</p>
        </div>
      </header>

      <div className="rounded-lg border border-border bg-background/60 p-4 space-y-3">
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="text-sm font-medium">{t('settings.privacy.sendReports')}</p>
            <p className="text-xs text-muted-foreground mt-0.5">
              {t('settings.privacy.sendReportsHint')}
            </p>
          </div>
          <label className="inline-flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              className="w-4 h-4 rounded accent-accent"
              checked={!optOut}
              disabled={saving}
              onChange={(e) => void toggleOptOut(!e.target.checked)}
            />
            <span className="text-sm">{!optOut ? t('common.on') : t('common.off')}</span>
          </label>
        </div>
      </div>

      <div className="rounded-lg border border-border bg-background/60 p-4 space-y-2">
        <p className="text-sm font-medium">{t('settings.privacy.currentStatus')}</p>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          {currentlySending ? (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/15 text-emerald-300 px-2.5 py-1">
              <CheckCircle2 className="w-3.5 h-3.5" /> {t('settings.privacy.sendingReports')}
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-muted text-muted-foreground px-2.5 py-1">
              <AlertTriangle className="w-3.5 h-3.5" /> {t('settings.privacy.disabled')}
            </span>
          )}
          {status?.environment && (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-muted px-2.5 py-1 text-muted-foreground">
              {t('settings.privacy.envLabel', { env: status.environment })}
            </span>
          )}
          {status?.release && (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-muted px-2.5 py-1 text-muted-foreground">
              {t('settings.privacy.releaseLabel', { release: status.release })}
            </span>
          )}
        </div>
        {!dsnConfigured && (
          <p className="text-xs text-muted-foreground mt-2">
            {t('settings.privacy.noDsnConfiguredPrefix')}{' '}
            <code className="px-1 py-0.5 rounded bg-muted text-foreground">
              DREVALIS_TELEMETRY_DSN
            </code>{' '}
            {t('settings.privacy.noDsnConfiguredSuffix')}
          </p>
        )}
      </div>

      <div className="flex justify-end">
        <Button variant="ghost" size="sm" onClick={() => void reload()}>
          {t('settings.privacy.refresh')}
        </Button>
      </div>
    </Card>
  );
}
