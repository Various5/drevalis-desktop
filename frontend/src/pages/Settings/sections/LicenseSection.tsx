import { useCallback, useEffect, useState } from 'react';
import {
  KeyRound,
  Copy,
  CheckCircle2,
  XCircle,
  Clock,
  AlertTriangle,
  ExternalLink,
  Monitor,
  Trash2,
  RefreshCw,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { useToast } from '@/components/ui/Toast';
import { license, formatError, type ActivationsResponse } from '@/lib/api';
import { useLicense } from '@/lib/useLicense';

function StateBadge({ state }: { state: string }) {
  const { t } = useTranslation();
  switch (state) {
    case 'active':
      return (
        <Badge variant="success">
          <CheckCircle2 size={12} className="mr-1" /> {t('settings.license.stateBadges.active')}
        </Badge>
      );
    case 'grace':
      return (
        <Badge variant="warning">
          <Clock size={12} className="mr-1" /> {t('settings.license.stateBadges.grace')}
        </Badge>
      );
    case 'expired':
      return (
        <Badge variant="error">
          <XCircle size={12} className="mr-1" /> {t('settings.license.stateBadges.expired')}
        </Badge>
      );
    case 'invalid':
      return (
        <Badge variant="error">
          <AlertTriangle size={12} className="mr-1" /> {t('settings.license.stateBadges.invalid')}
        </Badge>
      );
    default:
      return <Badge variant="default">{t('settings.license.stateBadges.unactivated')}</Badge>;
  }
}

// Tier visual treatment — prevents tier text from looking like a
// generic label among the other key-value rows. Each tier gets its
// own gradient-tinted pill so "Studio" reads as a status, not a word.
function TierBadge({ label }: { label: string }) {
  const lower = label.toLowerCase();
  let cls = 'border-white/10 bg-white/[0.04] text-txt-primary';
  if (lower.includes('lifetime')) {
    cls = 'border-amber-400/40 bg-amber-400/[0.08] text-amber-200';
  } else if (lower.includes('studio')) {
    cls = 'border-violet-400/40 bg-violet-400/[0.08] text-violet-200';
  } else if (lower.includes('pro')) {
    cls = 'border-accent/40 bg-accent/[0.08] text-accent';
  } else if (lower.includes('creator')) {
    cls = 'border-sky-400/40 bg-sky-400/[0.08] text-sky-200';
  }
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full border text-[11px] font-semibold uppercase tracking-wider ${cls}`}
    >
      {label}
    </span>
  );
}

// snake_case → Title Case for feature pills. "basic_generation" should
// read as "Basic Generation" not as a Python identifier.
function humanizeFeature(key: string): string {
  return key
    .split(/[_\s-]+/)
    .map((s) => (s ? s.charAt(0).toUpperCase() + s.slice(1).toLowerCase() : s))
    .join(' ');
}

function daysUntil(date: Date | null): number | null {
  if (!date) return null;
  const ms = date.getTime() - Date.now();
  return Math.ceil(ms / (24 * 3600 * 1000));
}

function tsToRelative(ts: number | null | undefined, t: TFunction): string {
  if (!ts) return t('settings.license.relativeTime.dash');
  const ms = ts < 1e12 ? ts * 1000 : ts; // unix seconds -> ms if needed
  const diff = Date.now() - ms;
  if (diff < 60_000) return t('settings.license.relativeTime.justNow');
  const mins = Math.floor(diff / 60_000);
  if (mins < 60) return t('settings.license.relativeTime.minAgo', { count: mins });
  const hrs = Math.floor(mins / 60);
  if (hrs < 48) return t('settings.license.relativeTime.hAgo', { count: hrs });
  const days = Math.floor(hrs / 24);
  return t('settings.license.relativeTime.dAgo', { count: days });
}

export function LicenseSection() {
  const { t } = useTranslation();
  const { status, loading, refresh } = useLicense();
  const { toast } = useToast();
  const [replaceKey, setReplaceKey] = useState('');
  const [replacing, setReplacing] = useState(false);
  const [deactivating, setDeactivating] = useState(false);
  const [openingPortal, setOpeningPortal] = useState(false);

  // Activations list (server-side seat tracking)
  const [activations, setActivations] = useState<ActivationsResponse | null>(null);
  const [activationsLoading, setActivationsLoading] = useState(false);
  const [deactivatingMachine, setDeactivatingMachine] = useState<string | null>(null);
  // Sticky failure for the seat-list endpoint — see comment below.
  const [activationsDisabled, setActivationsDisabled] = useState(false);

  // Narrow the useEffect trigger to the fields we actually read from
  // ``status`` — ``state`` is a primitive and ``activated_at`` only flips
  // on real changes. Using the object reference as a dependency would
  // re-fire this effect on every poll of the license status, producing
  // the toast flood bug.
  const licenseState = status?.state;
  const licenseActivatedAt = status?.activated_at;

  const loadActivations = useCallback(
    async (options: { manualRefresh?: boolean } = {}) => {
      if (!licenseState || licenseState === 'unactivated' || licenseState === 'invalid') {
        setActivations(null);
        return;
      }
      if (activationsDisabled && !options.manualRefresh) {
        return;
      }
      setActivationsLoading(true);
      try {
        const res = await license.listActivations();
        setActivations(res);
        if (activationsDisabled) setActivationsDisabled(false);
      } catch (e) {
        if (!activationsDisabled) {
          toast.warning(t('settings.license.seatList.warningTitle'), {
            description: t('settings.license.seatList.warningBody'),
          });
          setActivationsDisabled(true);
        }
        setActivations(null);
        // eslint-disable-next-line no-console
        console.debug('listActivations failed (auto-retry suppressed):', formatError(e));
      } finally {
        setActivationsLoading(false);
      }
    },
    [licenseState, activationsDisabled, toast, t],
  );

  useEffect(() => {
    loadActivations();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [licenseState, licenseActivatedAt]);

  const onDeactivateMachine = async (machineId: string) => {
    const isSelf = machineId === activations?.this_machine_id;
    const msg = isSelf
      ? t('settings.license.machines.confirmDeactivateSelf')
      : t('settings.license.machines.confirmDeactivateRemote', { machine: machineId.slice(0, 8) });
    if (!confirm(msg)) return;
    setDeactivatingMachine(machineId);
    try {
      const res = await license.deactivateMachine(machineId);
      setActivations(res);
      toast.success(
        isSelf
          ? t('settings.license.machines.selfDeactivatedToast')
          : t('settings.license.machines.seatReleasedToast'),
      );
      if (isSelf) {
        await refresh();
      }
    } catch (e) {
      toast.error(t('settings.license.machines.deactivationFailedToast'), { description: formatError(e) });
    } finally {
      setDeactivatingMachine(null);
    }
  };

  const onManageSubscription = async () => {
    setOpeningPortal(true);
    try {
      const r = await license.portal();
      if (r.url) {
        window.open(r.url, '_blank', 'noopener,noreferrer');
      } else {
        throw new Error('no portal url');
      }
    } catch (e: any) {
      const detail = e?.detail ?? e?.message ?? t('settings.license.manage.errorDefault');
      toast.error(t('settings.license.manage.errorTitle'), {
        description: typeof detail === 'string' ? detail : JSON.stringify(detail),
      });
    } finally {
      setOpeningPortal(false);
    }
  };

  const copyMachineId = async () => {
    if (!status?.machine_id) return;
    try {
      await navigator.clipboard.writeText(status.machine_id);
      toast.success(t('settings.license.machineIdCopiedToast'));
    } catch {
      toast.error(t('settings.license.copyFailedToast'));
    }
  };

  const onReplace = async () => {
    if (!replaceKey.trim()) return;
    setReplacing(true);
    try {
      await license.activate(replaceKey.trim());
      toast.success(t('settings.license.replace.successToast'));
      setReplaceKey('');
      refresh();
    } catch (e: any) {
      const detail = e?.detail ?? e?.message ?? t('settings.license.replace.errorDefault');
      toast.error(t('settings.license.replace.errorTitle'), {
        description: typeof detail === 'string' ? detail : JSON.stringify(detail),
      });
    } finally {
      setReplacing(false);
    }
  };

  const onDeactivate = async () => {
    if (!confirm(t('settings.license.deactivate.confirm'))) {
      return;
    }
    setDeactivating(true);
    try {
      await license.deactivate();
      toast.success(t('settings.license.deactivate.successToast'));
      refresh();
    } catch (e: any) {
      toast.error(t('settings.license.deactivate.failedToast'), { description: e?.message });
    } finally {
      setDeactivating(false);
    }
  };

  if (loading && !status) {
    return <Card className="p-6">{t('settings.license.loading')}</Card>;
  }

  const periodEnd = status?.period_end ? new Date(status.period_end) : null;
  const exp = status?.exp ? new Date(status.exp) : null;
  const isLifetime = status?.license_type === 'lifetime_pro';
  // Warn 14 days out so a lapsed renewal doesn't surprise the user.
  // Hard expiry is the cliff that locks the app (period_end has 7d grace).
  const expDays = daysUntil(exp);
  const expSoon = !isLifetime && expDays !== null && expDays >= 0 && expDays <= 14;
  const expPast = !isLifetime && expDays !== null && expDays < 0;
  const updateWindowEnds = status?.update_window_expires_at
    ? new Date(status.update_window_expires_at)
    : null;
  // Lifetime-upgrade CTA surfaces for subscription-Pro customers (any
  // interval). Creator / Studio paths stay on the subscription portal.
  const canUpgradeToLifetime =
    status?.state === 'active' && !isLifetime && status?.tier === 'pro';

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-lg font-semibold text-txt-primary flex items-center gap-2">
          <KeyRound size={18} /> {t('settings.license.heading')}
        </h3>
        <p className="text-xs text-txt-secondary mt-1">
          {t('settings.license.intro')}
        </p>
      </div>

      <Card className="p-5 space-y-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-xs text-txt-secondary mb-1">{t('settings.license.labels.status')}</div>
            <StateBadge state={status?.state ?? 'unactivated'} />
          </div>
          <div className="text-right">
            <div className="text-xs text-txt-secondary mb-1">{t('settings.license.labels.tier')}</div>
            <TierBadge label={isLifetime ? t('settings.license.tierLifetime') : (status?.tier ?? '—')} />
            {isLifetime && (
              <div className="text-[11px] text-amber-300 mt-1">
                {updateWindowEnds
                  ? t('settings.license.lifetimeUpdatesUntil', { date: updateWindowEnds.toLocaleDateString() })
                  : t('settings.license.labels.neverExpires')}
              </div>
            )}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4 pt-3 border-t border-white/[0.06]">
          <div>
            <div className="text-xs text-txt-secondary mb-1">
              {isLifetime ? t('settings.license.labels.licenseExpiry') : t('settings.license.labels.paidThrough')}
            </div>
            <div className="text-sm text-txt-primary">
              {isLifetime
                ? t('settings.license.labels.neverExpires')
                : periodEnd
                  ? periodEnd.toLocaleDateString()
                  : '—'}
            </div>
          </div>
          <div>
            <div className="text-xs text-txt-secondary mb-1">
              {isLifetime ? t('settings.license.labels.updatesIncludedUntil') : t('settings.license.labels.hardExpiry')}
            </div>
            <div
              className={`text-sm ${
                expPast ? 'text-error' : expSoon ? 'text-amber-300' : 'text-txt-primary'
              }`}
            >
              {isLifetime
                ? updateWindowEnds
                  ? updateWindowEnds.toLocaleDateString()
                  : '—'
                : exp
                  ? exp.toLocaleDateString()
                  : '—'}
            </div>
            {!isLifetime && expSoon && (
              <div className="text-[11px] text-amber-300 mt-0.5 flex items-center gap-1">
                <AlertTriangle size={11} />
                {expDays === 0
                  ? t('settings.license.expiresToday')
                  : t('settings.license.daysLeft', { count: expDays as number })}
              </div>
            )}
            {!isLifetime && expPast && (
              <div className="text-[11px] text-error mt-0.5 flex items-center gap-1">
                <AlertTriangle size={11} />
                {t('settings.license.expiredBadge')}
              </div>
            )}
          </div>
          <div>
            <div className="text-xs text-txt-secondary mb-1">{t('settings.license.labels.seatCap')}</div>
            <div className="text-sm text-txt-primary">
              {status?.machines_cap ?? '—'}{' '}
              {status?.machines_cap === 1
                ? t('settings.license.labels.machineSingular')
                : t('settings.license.labels.machinePlural')}
            </div>
          </div>
          <div>
            <div className="text-xs text-txt-secondary mb-1">{t('settings.license.labels.features')}</div>
            <div className="text-xs text-txt-primary flex flex-wrap gap-1">
              {(status?.features ?? []).length === 0 ? (
                <span className="text-txt-muted">—</span>
              ) : (
                (status?.features ?? []).map((f) => (
                  <span
                    key={f}
                    className="px-1.5 py-0.5 rounded bg-bg-hover text-txt-secondary"
                    title={f}
                  >
                    {humanizeFeature(f)}
                  </span>
                ))
              )}
            </div>
          </div>
        </div>

        <div className="pt-3 border-t border-white/[0.06]">
          <div className="text-xs text-txt-secondary mb-1">{t('settings.license.labels.thisMachine')}</div>
          <div className="flex items-center gap-2">
            <code className="text-xs font-mono text-txt-primary bg-bg-base px-2 py-1 rounded">
              {status?.machine_id ?? '—'}
            </code>
            <Button variant="ghost" size="sm" onClick={copyMachineId}>
              <Copy size={14} />
            </Button>
          </div>
          {status?.activated_at && (
            <div className="text-xs text-txt-secondary mt-1">
              {t('settings.license.labels.activatedAt', { date: new Date(status.activated_at).toLocaleString() })}
            </div>
          )}
        </div>
      </Card>

      {!isLifetime && (
        <Card className="p-5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h4 className="text-sm font-semibold text-txt-primary">{t('settings.license.manage.title')}</h4>
              <p className="text-xs text-txt-secondary mt-1">
                {t('settings.license.manage.intro')}
              </p>
            </div>
            <Button
              variant="secondary"
              size="md"
              onClick={onManageSubscription}
              disabled={openingPortal || status?.state !== 'active'}
            >
              {openingPortal ? t('settings.license.manage.opening') : <>{t('settings.license.manage.openPortal')} <ExternalLink size={14} /></>}
            </Button>
          </div>
        </Card>
      )}

      {isLifetime && (
        <Card
          className="p-5"
          style={{
            background: 'linear-gradient(135deg, rgba(251,191,36,0.06), rgba(20,22,27,0.8))',
            borderColor: 'rgba(251,191,36,0.25)',
          }}
        >
          <h4 className="text-sm font-semibold text-txt-primary mb-1">
            {t('settings.license.lifetime.title')}
          </h4>
          <p className="text-xs text-txt-secondary">
            {updateWindowEnds
              ? t('settings.license.lifetime.introWithDate', { date: updateWindowEnds.toLocaleDateString() })
              : t('settings.license.lifetime.introNoDate')}
          </p>
        </Card>
      )}

      {canUpgradeToLifetime && (
        <Card
          className="p-5"
          style={{
            background: 'linear-gradient(135deg, rgba(251,191,36,0.05), rgba(20,22,27,0.7))',
            borderColor: 'rgba(251,191,36,0.2)',
          }}
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <h4 className="text-sm font-semibold text-txt-primary">{t('settings.license.upgrade.title')}</h4>
              <p className="text-xs text-txt-secondary mt-1">
                {t('settings.license.upgrade.intro')}
              </p>
            </div>
            <Button
              variant="primary"
              size="md"
              onClick={() =>
                window.open('https://drevalis.com/pricing#plans', '_blank', 'noopener')
              }
            >
              {t('settings.license.upgrade.button')} <ExternalLink size={14} />
            </Button>
          </div>
        </Card>
      )}

      <Card className="p-5 space-y-3">
        <div>
          <h4 className="text-sm font-semibold text-txt-primary">{t('settings.license.replace.title')}</h4>
          <p className="text-xs text-txt-secondary mt-1">
            {t('settings.license.replace.intro')}
          </p>
        </div>
        <textarea
          value={replaceKey}
          onChange={(e) => setReplaceKey(e.target.value)}
          className="w-full h-24 px-3 py-2 bg-bg-base border border-white/[0.08] rounded-md text-xs font-mono text-txt-primary focus:outline-none focus:border-accent/40 resize-none"
          placeholder={t('settings.license.replace.placeholder')}
          spellCheck={false}
        />
        <div className="flex items-center justify-end">
          <Button variant="primary" size="md" onClick={onReplace} disabled={replacing || !replaceKey.trim()}>
            {replacing ? t('settings.license.replace.activating') : t('settings.license.replace.replace')}
          </Button>
        </div>
      </Card>

      {/* Activated machines (all seats held by this license) */}
      <Card className="p-5">
        <div className="flex items-start justify-between gap-3 mb-4">
          <div>
            <h4 className="text-sm font-semibold text-txt-primary flex items-center gap-2">
              <Monitor size={14} />
              {t('settings.license.machines.title')}
            </h4>
            <p className="text-xs text-txt-secondary mt-1">
              {activations
                ? t('settings.license.machines.introUsage', {
                    used: activations.activations.length,
                    cap: activations.cap,
                    tier: activations.tier,
                  })
                : t('settings.license.machines.introFallback')}
            </p>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => loadActivations({ manualRefresh: true })}
            disabled={activationsLoading}
            title={t('settings.license.machines.refreshTitle')}
          >
            <RefreshCw size={13} className={activationsLoading ? 'animate-spin' : ''} />
          </Button>
        </div>

        {activations === null ? (
          <div className="text-xs text-txt-muted py-3 text-center">
            {activationsLoading ? t('settings.license.machines.loading') : t('settings.license.machines.unavailable')}
          </div>
        ) : activations.activations.length === 0 ? (
          <div className="text-xs text-txt-muted py-3 text-center">
            {t('settings.license.machines.empty')}
          </div>
        ) : (
          <div className="space-y-2">
            {activations.activations.map((a) => (
              <div
                key={a.machine_id}
                className={[
                  'flex items-center justify-between gap-3 p-3 rounded border',
                  a.is_this_machine
                    ? 'border-accent/40 bg-accent/[0.04]'
                    : 'border-white/[0.06] bg-bg-elevated/50',
                ].join(' ')}
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <code className="text-xs font-mono text-txt-primary truncate">
                      {a.machine_id}
                    </code>
                    {a.is_this_machine && (
                      <Badge variant="success" className="text-[10px]">
                        {t('settings.license.machines.thisMachineBadge')}
                      </Badge>
                    )}
                    {a.last_known_version && (
                      <span className="text-[10px] text-txt-muted">
                        {t('settings.license.machines.versionPrefix')}{a.last_known_version}
                      </span>
                    )}
                  </div>
                  <div className="text-[11px] text-txt-muted mt-0.5">
                    {t('settings.license.machines.firstSeen', { when: tsToRelative(a.first_seen, t) })}
                    {' · '}
                    {t('settings.license.machines.lastHeartbeat', { when: tsToRelative(a.last_heartbeat, t) })}
                  </div>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onDeactivateMachine(a.machine_id)}
                  disabled={deactivatingMachine === a.machine_id}
                  className="shrink-0 text-error hover:bg-error/10"
                  title={
                    a.is_this_machine
                      ? t('settings.license.machines.deactivateSelfTitle')
                      : t('settings.license.machines.deactivateRemoteTitle')
                  }
                >
                  <Trash2 size={13} />
                  {deactivatingMachine === a.machine_id
                    ? t('settings.license.machines.deactivatingButton')
                    : t('settings.license.machines.deactivateButton')}
                </Button>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card className="p-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h4 className="text-sm font-semibold text-txt-primary">{t('settings.license.deactivate.title')}</h4>
            <p className="text-xs text-txt-secondary mt-1">
              {t('settings.license.deactivate.intro')}
            </p>
          </div>
          <Button variant="destructive" size="md" onClick={onDeactivate} disabled={deactivating}>
            {deactivating ? t('settings.license.deactivate.working') : t('settings.license.deactivate.button')}
          </Button>
        </div>
      </Card>
    </div>
  );
}

export default LicenseSection;
