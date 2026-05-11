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
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { useToast } from '@/components/ui/Toast';
import { license, formatError, type ActivationsResponse } from '@/lib/api';
import { useLicense } from '@/lib/useLicense';

function StateBadge({ state }: { state: string }) {
  switch (state) {
    case 'active':
      return (
        <Badge variant="success">
          <CheckCircle2 size={12} className="mr-1" /> Active
        </Badge>
      );
    case 'grace':
      return (
        <Badge variant="warning">
          <Clock size={12} className="mr-1" /> Grace period
        </Badge>
      );
    case 'expired':
      return (
        <Badge variant="error">
          <XCircle size={12} className="mr-1" /> Expired
        </Badge>
      );
    case 'invalid':
      return (
        <Badge variant="error">
          <AlertTriangle size={12} className="mr-1" /> Invalid
        </Badge>
      );
    default:
      return <Badge variant="default">Unactivated</Badge>;
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

function tsToRelative(ts: number | null | undefined): string {
  if (!ts) return '-';
  const ms = ts < 1e12 ? ts * 1000 : ts; // unix seconds -> ms if needed
  const diff = Date.now() - ms;
  if (diff < 60_000) return 'just now';
  const mins = Math.floor(diff / 60_000);
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 48) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

export function LicenseSection() {
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
  // Track whether we've already given up on the seat-list endpoint for
  // this session. An older license-server deployment (or a misconfigured
  // ``LICENSE_SERVER_URL``) returns 404 here; re-trying on every render
  // and toasting each time floods the UI. Sticky failure = silent after
  // the first warning, and only the explicit "Refresh" button retries.
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
        // A successful fetch re-enables the auto-refresh hook; the server
        // came back online or was just freshly deployed.
        if (activationsDisabled) setActivationsDisabled(false);
      } catch (e) {
        // Show the warning once, then stop auto-retrying so a broken
        // license-server doesn't produce hundreds of identical toasts.
        if (!activationsDisabled) {
          toast.warning('Seat list unavailable', {
            description:
              'The license server returned an error. This is typically a ' +
              'stale license-server deployment — your license still works. ' +
              'Use the refresh button above to retry.',
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
    [licenseState, activationsDisabled, toast],
  );

  useEffect(() => {
    loadActivations();
    // We intentionally only refresh on ``licenseState`` / ``licenseActivatedAt``,
    // not the full ``status`` object — see the ``licenseState`` comment above
    // for the toast-flood we were fixing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [licenseState, licenseActivatedAt]);

  const onDeactivateMachine = async (machineId: string) => {
    const isSelf = machineId === activations?.this_machine_id;
    const msg = isSelf
      ? "Deactivate THIS machine's seat? The app will lock until you paste a new license."
      : `Free the seat held by machine ${machineId.slice(0, 8)}...? The other install locks on its next heartbeat.`;
    if (!confirm(msg)) return;
    setDeactivatingMachine(machineId);
    try {
      const res = await license.deactivateMachine(machineId);
      setActivations(res);
      toast.success(isSelf ? 'This machine deactivated' : 'Seat released');
      if (isSelf) {
        // Our own JWT was cleared server-side AND locally; refresh status
        // so LicenseGate flips back to the activation wizard.
        await refresh();
      }
    } catch (e) {
      toast.error('Deactivation failed', { description: formatError(e) });
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
      const detail = e?.detail ?? e?.message ?? 'could not open billing portal';
      toast.error('Billing portal unavailable', {
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
      toast.success('Machine ID copied');
    } catch {
      toast.error('Copy failed');
    }
  };

  const onReplace = async () => {
    if (!replaceKey.trim()) return;
    setReplacing(true);
    try {
      await license.activate(replaceKey.trim());
      toast.success('License replaced');
      setReplaceKey('');
      refresh();
    } catch (e: any) {
      const detail = e?.detail ?? e?.message ?? 'activation failed';
      toast.error('Activation failed', {
        description: typeof detail === 'string' ? detail : JSON.stringify(detail),
      });
    } finally {
      setReplacing(false);
    }
  };

  const onDeactivate = async () => {
    if (!confirm('Deactivate license on this machine? The app will lock until you activate again.')) {
      return;
    }
    setDeactivating(true);
    try {
      await license.deactivate();
      toast.success('License deactivated');
      refresh();
    } catch (e: any) {
      toast.error('Deactivate failed', { description: e?.message });
    } finally {
      setDeactivating(false);
    }
  };

  if (loading && !status) {
    return <Card className="p-6">Loading license…</Card>;
  }

  const periodEnd = status?.period_end ? new Date(status.period_end) : null;
  const exp = status?.exp ? new Date(status.exp) : null;
  const isLifetime = status?.license_type === 'lifetime_pro';
  // Warn the user 14 days out so a lapsed renewal doesn't surprise
  // them. We use the hard expiry rather than the period_end because
  // that's the cliff that actually locks the app (period_end has 7d
  // grace beyond it).
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
          <KeyRound size={18} /> License
        </h3>
        <p className="text-xs text-txt-secondary mt-1">
          Your subscription entitlements and seat information.
        </p>
      </div>

      <Card className="p-5 space-y-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-xs text-txt-secondary mb-1">Status</div>
            <StateBadge state={status?.state ?? 'unactivated'} />
          </div>
          <div className="text-right">
            <div className="text-xs text-txt-secondary mb-1">Tier</div>
            <TierBadge label={isLifetime ? 'Lifetime (Pro)' : (status?.tier ?? '—')} />
            {isLifetime && (
              <div className="text-[11px] text-amber-300 mt-1">
                {updateWindowEnds
                  ? `Updates included until ${updateWindowEnds.toLocaleDateString()}`
                  : 'Never expires'}
              </div>
            )}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4 pt-3 border-t border-white/[0.06]">
          <div>
            <div className="text-xs text-txt-secondary mb-1">
              {isLifetime ? 'License' : 'Paid through'}
            </div>
            <div className="text-sm text-txt-primary">
              {isLifetime
                ? 'Never expires'
                : periodEnd
                  ? periodEnd.toLocaleDateString()
                  : '—'}
            </div>
          </div>
          <div>
            <div className="text-xs text-txt-secondary mb-1">
              {isLifetime ? 'Updates included until' : 'Hard expiry (+ 7d grace)'}
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
                  ? 'Expires today'
                  : `${expDays} day${expDays === 1 ? '' : 's'} left`}
              </div>
            )}
            {!isLifetime && expPast && (
              <div className="text-[11px] text-error mt-0.5 flex items-center gap-1">
                <AlertTriangle size={11} />
                Expired
              </div>
            )}
          </div>
          <div>
            <div className="text-xs text-txt-secondary mb-1">Seat cap</div>
            <div className="text-sm text-txt-primary">
              {status?.machines_cap ?? '—'} {status?.machines_cap === 1 ? 'machine' : 'machines'}
            </div>
          </div>
          <div>
            <div className="text-xs text-txt-secondary mb-1">Features</div>
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
          <div className="text-xs text-txt-secondary mb-1">This machine</div>
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
              Activated {new Date(status.activated_at).toLocaleString()}
            </div>
          )}
        </div>
      </Card>

      {!isLifetime && (
        <Card className="p-5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h4 className="text-sm font-semibold text-txt-primary">Manage subscription</h4>
              <p className="text-xs text-txt-secondary mt-1">
                Upgrade, downgrade, change payment method, view invoices, or cancel — handled by Stripe's billing portal.
              </p>
            </div>
            <Button
              variant="secondary"
              size="md"
              onClick={onManageSubscription}
              disabled={openingPortal || status?.state !== 'active'}
            >
              {openingPortal ? 'Opening…' : <>Open portal <ExternalLink size={14} /></>}
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
            Lifetime (Pro) — thank you.
          </h4>
          <p className="text-xs text-txt-secondary">
            Your license is permanent. There's no billing portal, nothing to renew. Updates are bundled through
            {updateWindowEnds ? ` ${updateWindowEnds.toLocaleDateString()}` : ' your included window'};
            after that the app keeps working and you can extend updates
            anytime from your account page.
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
              <h4 className="text-sm font-semibold text-txt-primary">Upgrade to Lifetime (Pro)</h4>
              <p className="text-xs text-txt-secondary mt-1">
                One-time CHF 899. Keeps the Pro feature set, never renews. 3 years of updates included.
                Limited to the first 100 seats.
              </p>
            </div>
            <Button
              variant="primary"
              size="md"
              onClick={() =>
                window.open('https://drevalis.com/pricing#plans', '_blank', 'noopener')
              }
            >
              Upgrade <ExternalLink size={14} />
            </Button>
          </div>
        </Card>
      )}

      <Card className="p-5 space-y-3">
        <div>
          <h4 className="text-sm font-semibold text-txt-primary">Replace license key</h4>
          <p className="text-xs text-txt-secondary mt-1">
            Paste a new JWT to switch tier or extend the subscription.
          </p>
        </div>
        <textarea
          value={replaceKey}
          onChange={(e) => setReplaceKey(e.target.value)}
          className="w-full h-24 px-3 py-2 bg-bg-base border border-white/[0.08] rounded-md text-xs font-mono text-txt-primary focus:outline-none focus:border-accent/40 resize-none"
          placeholder="eyJhbGciOiJFZERTQSI..."
          spellCheck={false}
        />
        <div className="flex items-center justify-end">
          <Button variant="primary" size="md" onClick={onReplace} disabled={replacing || !replaceKey.trim()}>
            {replacing ? 'Activating…' : 'Replace'}
          </Button>
        </div>
      </Card>

      {/* Activated machines (all seats held by this license) */}
      <Card className="p-5">
        <div className="flex items-start justify-between gap-3 mb-4">
          <div>
            <h4 className="text-sm font-semibold text-txt-primary flex items-center gap-2">
              <Monitor size={14} />
              Activated machines
            </h4>
            <p className="text-xs text-txt-secondary mt-1">
              {activations
                ? `${activations.activations.length} of ${activations.cap} seats used on your ${activations.tier} tier.`
                : 'Seats currently held by this license key.'}
            </p>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => loadActivations({ manualRefresh: true })}
            disabled={activationsLoading}
            title="Re-check seat list"
          >
            <RefreshCw size={13} className={activationsLoading ? 'animate-spin' : ''} />
          </Button>
        </div>

        {activations === null ? (
          <div className="text-xs text-txt-muted py-3 text-center">
            {activationsLoading ? 'Loading...' : 'Seat list not available.'}
          </div>
        ) : activations.activations.length === 0 ? (
          <div className="text-xs text-txt-muted py-3 text-center">
            No machines currently registered.
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
                        This machine
                      </Badge>
                    )}
                    {a.last_known_version && (
                      <span className="text-[10px] text-txt-muted">v{a.last_known_version}</span>
                    )}
                  </div>
                  <div className="text-[11px] text-txt-muted mt-0.5">
                    First seen {tsToRelative(a.first_seen)} &middot; Last heartbeat{' '}
                    {tsToRelative(a.last_heartbeat)}
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
                      ? 'Deactivate this machine (the app will lock)'
                      : 'Free the seat held by this remote machine'
                  }
                >
                  <Trash2 size={13} />
                  {deactivatingMachine === a.machine_id ? 'Working...' : 'Deactivate'}
                </Button>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card className="p-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h4 className="text-sm font-semibold text-txt-primary">Deactivate this machine</h4>
            <p className="text-xs text-txt-secondary mt-1">
              Clears the stored license. The app will lock until a new key is pasted. Equivalent to
              hitting &ldquo;Deactivate&rdquo; next to the highlighted row above.
            </p>
          </div>
          <Button variant="destructive" size="md" onClick={onDeactivate} disabled={deactivating}>
            {deactivating ? 'Working...' : 'Deactivate'}
          </Button>
        </div>
      </Card>
    </div>
  );
}

export default LicenseSection;
