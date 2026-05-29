import { useCallback, useEffect, useState } from 'react';
import {
  ArrowUpCircle,
  CheckCircle2,
  AlertTriangle,
  RefreshCw,
  Search,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { useToast } from '@/components/ui/Toast';
import {
  checkTauriUpdate,
  installTauriUpdate,
  type TauriUpdateInfo,
  type TauriUpdateProgress,
  type UpdaterChannel,
} from '@/lib/tauri';
import { formatError } from '@/lib/api';

/**
 * Desktop ("Tauri") update flow. Talks to the Tauri auto-updater plugin
 * which:
 *  - hits a signed manifest at the GitHub Releases URL configured in
 *    tauri.conf.json (plugins.updater.endpoints);
 *  - downloads + verifies + installs the update in place;
 *  - exits the running app and re-launches the new install.
 *
 * The user never has to re-download the installer manually. Replaces
 * the legacy Docker "pull new images and restart the stack" flow that
 * lives in UpdatesSection.tsx for the (deprecated) server install.
 */
export function TauriUpdatesSection() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const [info, setInfo] = useState<TauriUpdateInfo | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [progress, setProgress] = useState<TauriUpdateProgress | null>(null);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);
  // Phase 6 — update channel preference. Defaults to 'stable' per the
  // release plan; loaded from /auth/preferences once on mount. Until
  // the user touches the picker, ``null`` means "preference not yet
  // fetched" — we still use 'stable' as the effective default so the
  // first check on app launch doesn't sit idle.
  const [channel, setChannel] = useState<UpdaterChannel>('stable');
  const [channelLoaded, setChannelLoaded] = useState(false);
  const [savingChannel, setSavingChannel] = useState(false);

  // Load update_channel preference once on mount. Backend stores
  // arbitrary keys on the auth/preferences endpoint; missing key
  // means "stable" (the default).
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const res = await fetch('/api/v1/auth/preferences', { credentials: 'include' });
        if (!res.ok) {
          if (!cancelled) setChannelLoaded(true);
          return;
        }
        const prefs = (await res.json()) as { update_channel?: string };
        if (!cancelled) {
          if (prefs.update_channel === 'rc') setChannel('rc');
          setChannelLoaded(true);
        }
      } catch {
        if (!cancelled) setChannelLoaded(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const onChangeChannel = async (next: UpdaterChannel) => {
    setSavingChannel(true);
    const previous = channel;
    setChannel(next);
    try {
      const res = await fetch('/api/v1/auth/preferences', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        // Persist 'rc' explicitly; 'stable' (the default) is stored
        // as null so the JSON column doesn't carry redundant keys.
        body: JSON.stringify({ update_channel: next === 'rc' ? 'rc' : null }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
    } catch (err) {
      // Roll back the optimistic toggle if the persist failed —
      // otherwise the user sees "rc" selected but the next check
      // still hits stable.
      setChannel(previous);
      toast.error(t('settings.updates.tauri.channelSaveFailed'), { description: formatError(err) });
    } finally {
      setSavingChannel(false);
    }
  };

  const refresh = useCallback(
    async (surfaceResult: boolean) => {
      setRefreshing(true);
      try {
        const result = await checkTauriUpdate(channel);
        setInfo(result);
        setLastChecked(new Date());
        if (surfaceResult) {
          if (result.available) {
            toast.success(t('settings.updates.tauri.newVersionToast', { version: result.version }));
          } else {
            toast.success(t('settings.updates.tauri.onLatestToast'), {
              description: result.currentVersion
                ? t('settings.updates.tauri.onLatestToastDesc', { version: result.currentVersion })
                : undefined,
            });
          }
        }
      } catch (e) {
        toast.error(t('settings.updates.tauri.checkFailed'), {
          description: e instanceof Error ? e.message : String(e),
        });
      } finally {
        setRefreshing(false);
      }
    },
    [toast, t, channel],
  );

  // Initial fetch (no toast). Hold off until the channel preference
  // has loaded — otherwise the first check could hit the wrong
  // manifest, briefly show "no update available" for an rc-channel
  // user, then re-check on the second render.
  useEffect(() => {
    if (!channelLoaded) return;
    void refresh(false);
  }, [refresh, channelLoaded]);

  const onInstall = async () => {
    if (!confirm(t('settings.updates.tauri.confirmInstall'))) {
      return;
    }
    setInstalling(true);
    setProgress({ phase: 'started' });
    try {
      await installTauriUpdate((p) => setProgress(p), channel);
      // If we get here without restart, surface a final toast.
      toast.success(t('settings.updates.tauri.installedToast'), {
        description: t('settings.updates.tauri.installedToastDesc'),
      });
    } catch (e) {
      toast.error(t('settings.updates.tauri.installFailed'), {
        description: e instanceof Error ? e.message : String(e),
      });
    } finally {
      setInstalling(false);
    }
  };

  const downloadedMB =
    progress?.downloaded != null
      ? (progress.downloaded / 1024 / 1024).toFixed(1)
      : null;
  const totalMB =
    progress?.total != null ? (progress.total / 1024 / 1024).toFixed(1) : null;

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h3 className="text-lg font-semibold text-txt-primary flex items-center gap-2">
            <ArrowUpCircle size={18} /> {t('settings.updates.heading')}
          </h3>
          <p className="text-xs text-txt-secondary mt-1">
            {t('settings.updates.tauri.intro')}
          </p>
          {lastChecked && (
            <p className="text-[11px] text-txt-muted mt-1">
              {t('settings.updates.tauri.lastCheckedTime', { time: lastChecked.toLocaleTimeString() })}
            </p>
          )}
        </div>
        <Button
          variant="primary"
          size="md"
          onClick={() => refresh(true)}
          disabled={refreshing || installing}
          className="shrink-0"
        >
          <Search size={15} className={refreshing ? 'animate-pulse' : ''} />
          {refreshing ? t('settings.updates.checking') : t('settings.updates.checkForUpdates')}
        </Button>
      </div>

      <Card className="p-5 space-y-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-xs text-txt-secondary mb-1">{t('settings.updates.labels.installed')}</div>
            <div className="text-lg font-semibold text-txt-primary">
              {info?.currentVersion ? `v${info.currentVersion}` : '-'}
            </div>
          </div>
          <div className="text-right">
            <div className="text-xs text-txt-secondary mb-1">{t('settings.updates.labels.latest')}</div>
            <div className="text-lg font-semibold text-txt-primary">
              {info?.available && info.version
                ? `v${info.version}`
                : info?.currentVersion
                  ? `v${info.currentVersion}`
                  : '-'}
            </div>
          </div>
        </div>

        {info == null ? (
          <div className="p-3 rounded border border-white/10 bg-white/5 text-xs text-txt-secondary">
            {t('settings.updates.tauri.noChecksYet')}
          </div>
        ) : info.available ? (
          <div className="p-3 rounded border border-accent/30 bg-accent/10 text-xs text-accent flex items-start gap-2">
            <ArrowUpCircle size={14} className="mt-0.5 shrink-0" />
            <div>
              <div className="font-semibold">{t('settings.updates.tauri.updateAvailable', { version: info.version })}</div>
              {info.body && (
                <pre className="mt-2 whitespace-pre-wrap font-sans text-[11px] text-accent/80 max-h-40 overflow-auto">
                  {info.body}
                </pre>
              )}
            </div>
          </div>
        ) : (
          <div className="p-3 rounded border border-success/30 bg-success/10 text-xs text-success flex items-center gap-2">
            <CheckCircle2 size={14} />
            {t('settings.updates.tauri.onLatest')}
          </div>
        )}

        {installing && progress && (
          <div className="p-3 rounded border border-accent/30 bg-accent/10 text-xs text-accent">
            {progress.phase === 'started' && t('settings.updates.tauri.progress.starting')}
            {progress.phase === 'progress' && (
              totalMB
                ? t('settings.updates.tauri.progress.downloadingOf', { downloaded: downloadedMB ?? '?', total: totalMB })
                : t('settings.updates.tauri.progress.downloading', { downloaded: downloadedMB ?? '?' })
            )}
            {progress.phase === 'finished' && t('settings.updates.tauri.progress.installing')}
          </div>
        )}

        <div className="flex items-center justify-between pt-3 border-t border-white/[0.06]">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => refresh(true)}
            disabled={refreshing || installing}
          >
            <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
            {t('settings.updates.checkAgain')}
          </Button>
          <Button
            variant="primary"
            size="md"
            onClick={onInstall}
            disabled={installing || !info?.available}
          >
            {installing ? t('settings.updates.installing') : t('settings.updates.updateNow')}
          </Button>
        </div>

        {/* Channel picker — Stable (default) vs Release candidate. */}
        <div className="pt-3 border-t border-white/[0.06] space-y-2">
          <div className="text-xs font-medium text-txt-secondary">
            {t('settings.updates.tauri.channelLabel')}
          </div>
          <fieldset className="flex gap-2" disabled={savingChannel || installing}>
            <legend className="sr-only">{t('settings.updates.tauri.channelLabel')}</legend>
            {(['stable', 'rc'] as const).map((c) => {
              const active = channel === c;
              return (
                <label
                  key={c}
                  className={[
                    'flex-1 cursor-pointer rounded-md border px-3 py-2 text-xs text-center transition-colors',
                    active
                      ? 'border-accent bg-accent/10 text-accent'
                      : 'border-border bg-bg-elevated text-txt-secondary hover:bg-bg-hover hover:text-txt-primary',
                    (savingChannel || installing) && 'opacity-60 cursor-not-allowed',
                  ].filter(Boolean).join(' ')}
                >
                  <input
                    type="radio"
                    name="update-channel"
                    value={c}
                    checked={active}
                    onChange={() => void onChangeChannel(c)}
                    className="sr-only"
                  />
                  {c === 'stable'
                    ? t('settings.updates.tauri.channelStable')
                    : t('settings.updates.tauri.channelRc')}
                </label>
              );
            })}
          </fieldset>
          <p className="text-[11px] text-txt-tertiary leading-relaxed">
            {t('settings.updates.tauri.channelHint')}
          </p>
        </div>
      </Card>

      <div className="text-[11px] text-txt-muted flex items-start gap-2">
        <AlertTriangle size={12} className="mt-0.5 shrink-0" />
        <span>{t('settings.updates.tauri.trustNote')}</span>
      </div>
    </div>
  );
}
