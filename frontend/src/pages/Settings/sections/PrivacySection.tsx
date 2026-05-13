import { useEffect, useState } from 'react';
import { ShieldCheck, AlertTriangle, CheckCircle2 } from 'lucide-react';
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

  if (loading) return <Card className="p-6">Loading privacy settings...</Card>;

  const dsnConfigured = Boolean(status?.dsn) || Boolean(status?.environment);
  const currentlySending = Boolean(status?.enabled) && Boolean(status?.dsn);

  return (
    <Card className="p-6 space-y-6">
      <header className="flex items-start gap-3">
        <ShieldCheck className="w-6 h-6 text-accent flex-shrink-0 mt-0.5" />
        <div>
          <h2 className="text-lg font-semibold">Privacy & Crash Reporting</h2>
          <p className="text-sm text-muted-foreground mt-1">
            Anonymous crash reports help us catch and fix bugs in the alpha
            faster. No content, file paths, or credentials are ever sent —
            only the exception type, stack trace, and app version. You can
            opt out at any time.
          </p>
        </div>
      </header>

      <div className="rounded-lg border border-border bg-background/60 p-4 space-y-3">
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="text-sm font-medium">Send crash reports</p>
            <p className="text-xs text-muted-foreground mt-0.5">
              When enabled, exceptions in the backend, frontend, and desktop
              shell are sent to the configured error-tracking backend.
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
            <span className="text-sm">{!optOut ? 'On' : 'Off'}</span>
          </label>
        </div>
      </div>

      <div className="rounded-lg border border-border bg-background/60 p-4 space-y-2">
        <p className="text-sm font-medium">Current status</p>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          {currentlySending ? (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/15 text-emerald-300 px-2.5 py-1">
              <CheckCircle2 className="w-3.5 h-3.5" /> Sending reports
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-muted text-muted-foreground px-2.5 py-1">
              <AlertTriangle className="w-3.5 h-3.5" /> Disabled
            </span>
          )}
          {status?.environment && (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-muted px-2.5 py-1 text-muted-foreground">
              env: {status.environment}
            </span>
          )}
          {status?.release && (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-muted px-2.5 py-1 text-muted-foreground">
              release: {status.release}
            </span>
          )}
        </div>
        {!dsnConfigured && (
          <p className="text-xs text-muted-foreground mt-2">
            No telemetry backend is configured. Set{' '}
            <code className="px-1 py-0.5 rounded bg-muted text-foreground">
              DREVALIS_TELEMETRY_DSN
            </code>{' '}
            to point at your Sentry or Glitchtip project to enable
            crash reporting.
          </p>
        )}
      </div>

      <div className="flex justify-end">
        <Button variant="ghost" size="sm" onClick={() => void reload()}>
          Refresh status
        </Button>
      </div>
    </Card>
  );
}
