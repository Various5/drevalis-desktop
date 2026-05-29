import { useCallback, useEffect, useState } from 'react';
import {
  ArrowUpCircle,
  CheckCircle2,
  AlertTriangle,
  RefreshCw,
  ExternalLink,
  Search,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { useToast } from '@/components/ui/Toast';
import { UpdateProgressOverlay } from '@/components/UpdateProgressOverlay';
import {
  updates,
  type UpdateStatus,
  type ChangelogEntry,
  formatError,
} from '@/lib/api';
import { isTauri } from '@/lib/tauri';
import { TauriUpdatesSection } from './TauriUpdatesSection';

/** Human-readable "2 minutes ago" from a Date. */
function timeAgo(d: Date, t: TFunction): string {
  const secs = Math.max(0, Math.floor((Date.now() - d.getTime()) / 1000));
  if (secs < 5) return t('settings.updates.relativeTime.justNow');
  if (secs < 60) return t('settings.updates.relativeTime.secAgo', { count: secs });
  const mins = Math.floor(secs / 60);
  if (mins < 60) return t('settings.updates.relativeTime.minAgo', { count: mins });
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return t('settings.updates.relativeTime.hAgo', { count: hrs });
  const days = Math.floor(hrs / 24);
  return t('settings.updates.relativeTime.dAgo', { count: days });
}

const KNOWN_REASONS = new Set([
  'license_required',
  'license_revoked',
  'license_expired',
  'license_server_not_configured',
  'network_error',
]);

export function UpdatesSection() {
  // Inside the Tauri desktop shell, route through the auto-updater
  // plugin (signed manifest at the configured GitHub Releases URL,
  // in-place install, app re-launches itself). The Docker-flag-file
  // flow below stays for the (deprecated) server install where this
  // SPA might still be served by a Docker stack with a sidecar
  // listening for /tmp/update.flag.
  if (isTauri()) {
    return <TauriUpdatesSection />;
  }

  return <LegacyDockerUpdatesSection />;
}

function LegacyDockerUpdatesSection() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const [status, setStatus] = useState<UpdateStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [applying, setApplying] = useState(false);
  const [overlayOpen, setOverlayOpen] = useState(false);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);
  const [changelog, setChangelog] = useState<ChangelogEntry[]>([]);
  const [changelogLoading, setChangelogLoading] = useState(true);
  const [changelogError, setChangelogError] = useState<string | null>(null);
  const [changelogCached, setChangelogCached] = useState(false);

  const refresh = useCallback(
    async (force: boolean, surfaceResult: boolean) => {
      if (force) setRefreshing(true);
      else setLoading(true);
      try {
        const s = await updates.status(force);
        setStatus(s);
        setLastChecked(new Date());
        if (surfaceResult) {
          if (s.unavailable) {
            toast.warning(t('settings.updates.legacy.toasts.noDataTitle'), {
              description: s.reason ?? t('settings.updates.legacy.toasts.noDataDescFallback'),
            });
          } else if (s.update_available) {
            toast.success(
              t('settings.updates.legacy.toasts.updateAvailableTitlePrefix', {
                version: s.current_stable ?? t('settings.updates.legacy.toasts.newVersionFallback'),
              }),
              {
                description: s.mandatory_security_update
                  ? t('settings.updates.legacy.toasts.securityUpdateDesc')
                  : t('settings.updates.legacy.toasts.clickUpdateDesc'),
              },
            );
          } else {
            toast.success(t('settings.updates.legacy.toasts.onLatestTitle'), {
              description: t('settings.updates.legacy.toasts.onLatestDesc', {
                version: s.current_installed ?? '-',
              }),
            });
          }
        }
      } catch (e) {
        toast.error(t('settings.updates.legacy.toasts.checkFailed'), { description: formatError(e) });
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [toast, t],
  );

  useEffect(() => {
    // Initial fetch: no toast, just populate.
    refresh(false, false);
  }, [refresh]);

  const loadChangelog = useCallback(async (force: boolean) => {
    setChangelogLoading(true);
    try {
      const r = await updates.changelog(force, 20);
      setChangelog(r.entries ?? []);
      setChangelogCached(r.cached);
      setChangelogError(r.error ?? null);
    } catch (e) {
      setChangelogError(formatError(e));
    } finally {
      setChangelogLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadChangelog(false);
  }, [loadChangelog]);

  // Re-render the "last checked" label once a minute so it stays accurate
  // without the user clicking around.
  const [, bumpTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => bumpTick((tick) => tick + 1), 60_000);
    return () => clearInterval(id);
  }, []);

  const onApply = async () => {
    if (!confirm(t('settings.updates.legacy.confirmApply'))) {
      return;
    }
    setApplying(true);
    try {
      await updates.apply();
      // Surface the overlay immediately so the user has something to
      // watch while the updater sidecar picks up the flag.
      setOverlayOpen(true);
    } catch (e) {
      toast.error(t('settings.updates.legacy.queueFailed'), { description: formatError(e) });
    } finally {
      setApplying(false);
    }
  };

  if (loading) {
    return <Card className="p-6">{t('settings.updates.legacy.checkingForUpdates')}</Card>;
  }

  if (!status) {
    return <Card className="p-6">{t('settings.updates.legacy.noInfo')}</Card>;
  }

  const reasonKey = status.reason && KNOWN_REASONS.has(status.reason)
    ? `settings.updates.legacy.reasons.${status.reason}`
    : null;

  return (
    <div className="space-y-4">
      <UpdateProgressOverlay open={overlayOpen} onClose={() => setOverlayOpen(false)} />

      {/* Header + prominent Check button */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h3 className="text-lg font-semibold text-txt-primary flex items-center gap-2">
            <ArrowUpCircle size={18} /> {t('settings.updates.heading')}
          </h3>
          <p className="text-xs text-txt-secondary mt-1">
            {t('settings.updates.legacy.intro')}
          </p>
          {lastChecked && (
            <p className="text-[11px] text-txt-muted mt-1">
              {t('settings.updates.lastChecked', { when: timeAgo(lastChecked, t) })}
            </p>
          )}
        </div>
        <Button
          variant="primary"
          size="md"
          onClick={() => refresh(true, true)}
          disabled={refreshing}
          className="shrink-0"
          title={t('settings.updates.legacy.forceCheckTitle')}
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
              {status.current_installed ?? '-'}
            </div>
          </div>
          <div className="text-right">
            <div className="text-xs text-txt-secondary mb-1">{t('settings.updates.labels.latestStable')}</div>
            <div className="text-lg font-semibold text-txt-primary">
              {status.current_stable ?? '-'}
            </div>
          </div>
        </div>

        {status.unavailable ? (
          <div className="p-3 rounded border border-amber-500/30 bg-amber-500/10 text-xs text-amber-200 flex items-start gap-2">
            <AlertTriangle size={14} className="mt-0.5 shrink-0" />
            <div>
              <div className="font-semibold">{t('settings.updates.legacy.unavailableTitle')}</div>
              <div className="mt-0.5 text-amber-200/80">
                {reasonKey
                  ? t(reasonKey)
                  : t('settings.updates.legacy.reasons.fallback', {
                      reason: status.reason ?? t('settings.updates.legacy.reasons.unknown'),
                    })}
              </div>
            </div>
          </div>
        ) : status.update_available ? (
          <div className="p-3 rounded border border-accent/30 bg-accent/10 text-xs text-accent flex items-start gap-2">
            <ArrowUpCircle size={14} className="mt-0.5 shrink-0" />
            <div>
              <div className="font-semibold">
                {status.mandatory_security_update
                  ? t('settings.updates.legacy.updateAvailableSecurity')
                  : t('settings.updates.legacy.updateAvailable')}
              </div>
              {status.changelog_url && (
                <a
                  href={status.changelog_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 mt-0.5 underline hover:no-underline"
                >
                  {t('settings.updates.legacy.viewChangelog')} <ExternalLink size={11} />
                </a>
              )}
            </div>
          </div>
        ) : (
          <div className="p-3 rounded border border-success/30 bg-success/10 text-xs text-success flex items-center gap-2">
            <CheckCircle2 size={14} />
            {t('settings.updates.legacy.onLatest')}
          </div>
        )}

        <div className="flex items-center justify-between pt-3 border-t border-white/[0.06]">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => refresh(true, true)}
            disabled={refreshing}
            title={t('settings.updates.legacy.alsoTriggers')}
          >
            <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
            {t('settings.updates.checkAgain')}
          </Button>
          <Button
            variant="primary"
            size="md"
            onClick={onApply}
            disabled={applying || !status.update_available || status.unavailable}
          >
            {applying ? t('settings.updates.queueing') : t('settings.updates.updateNow')}
          </Button>
        </div>

        {status.image_tags && Object.keys(status.image_tags).length > 0 && (
          <div className="pt-3 border-t border-white/[0.06]">
            <div className="text-xs text-txt-secondary mb-2">{t('settings.updates.legacy.imageTagsTitle')}</div>
            <div className="space-y-1">
              {Object.entries(status.image_tags).map(([service, tag]) => (
                <div key={service} className="flex items-center justify-between text-xs">
                  <span className="text-txt-secondary">{service}</span>
                  <code className="font-mono text-txt-primary bg-bg-base px-2 py-0.5 rounded">
                    {tag}
                  </code>
                </div>
              ))}
            </div>
          </div>
        )}
      </Card>

      {/* ── Changelog — pulled from GitHub releases ─────────────── */}
      <Card className="p-5 space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h4 className="text-sm font-semibold text-txt-primary">
              {t('settings.updates.legacy.changelog.heading')}
            </h4>
            <p className="text-xs text-txt-secondary mt-1">
              {t('settings.updates.legacy.changelog.intro')}
              {changelogCached && (
                <span className="ml-1 text-txt-muted">{t('settings.updates.legacy.changelog.cached')}</span>
              )}
            </p>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void loadChangelog(true)}
            disabled={changelogLoading}
            title={t('settings.updates.legacy.changelog.refreshTitle')}
          >
            <RefreshCw
              size={13}
              className={changelogLoading ? 'animate-spin' : ''}
            />
            {t('settings.updates.legacy.changelog.refresh')}
          </Button>
        </div>

        {changelogError && (
          <div className="text-[11px] text-amber-300 bg-amber-500/10 border border-amber-500/30 rounded p-2">
            {changelogError}
          </div>
        )}

        {changelogLoading && changelog.length === 0 ? (
          <div className="text-xs text-txt-muted py-4 text-center">
            {t('settings.updates.legacy.changelog.loading')}
          </div>
        ) : changelog.length === 0 ? (
          <div className="text-xs text-txt-muted py-4 text-center">
            {t('settings.updates.legacy.changelog.empty')}
          </div>
        ) : (
          <div className="space-y-4 max-h-[480px] overflow-y-auto pr-1">
            {changelog.map((entry) => {
              const published = entry.published_at
                ? new Date(entry.published_at).toLocaleDateString()
                : null;
              const isCurrent =
                status.current_installed &&
                entry.version.replace(/^v/, '') ===
                  status.current_installed.replace(/^v/, '');
              return (
                <div
                  key={entry.version}
                  className={[
                    'rounded border p-3',
                    isCurrent
                      ? 'border-accent/40 bg-accent/[0.05]'
                      : 'border-white/[0.06] bg-bg-elevated/40',
                  ].join(' ')}
                >
                  <div className="flex items-center gap-2 flex-wrap mb-1">
                    <code className="font-mono text-sm font-semibold text-txt-primary">
                      {entry.version}
                    </code>
                    {entry.name && entry.name !== entry.version && (
                      <span className="text-xs text-txt-secondary">
                        — {entry.name}
                      </span>
                    )}
                    {entry.is_prerelease && (
                      <span className="text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300">
                        {t('settings.updates.legacy.changelog.preRelease')}
                      </span>
                    )}
                    {isCurrent && (
                      <span className="text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-accent/20 text-accent">
                        {t('settings.updates.legacy.changelog.installedBadge')}
                      </span>
                    )}
                    {published && (
                      <span className="text-[11px] text-txt-muted ml-auto">
                        {published}
                      </span>
                    )}
                    {entry.html_url && (
                      <a
                        href={entry.html_url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-txt-muted hover:text-accent"
                        title={t('settings.updates.legacy.changelog.openOnGitHub')}
                      >
                        <ExternalLink size={11} />
                      </a>
                    )}
                  </div>
                  {entry.body ? (
                    <pre className="whitespace-pre-wrap text-[11px] leading-relaxed text-txt-secondary font-sans break-words">
                      {entry.body}
                    </pre>
                  ) : (
                    <div className="text-[11px] text-txt-muted italic">
                      {t('settings.updates.legacy.changelog.noNotes')}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </Card>
    </div>
  );
}

export default UpdatesSection;
