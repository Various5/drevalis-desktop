import { useState } from 'react';
import { Trash2, Monitor } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { license, type ActivationsResponse } from '@/lib/api';

interface Props {
  status: 'unactivated' | 'expired' | 'invalid';
  stateError?: string | null;
  machineId?: string;
  onActivated: () => void;
}

/**
 * Full-screen activation wizard shown when no valid license is present.
 * Paste a license JWT → POST /api/v1/license/activate → parent refreshes
 * status on success and unmounts this.
 */
export function ActivationWizard({ status, stateError, machineId, onActivated }: Props) {
  const [key, setKey] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Seat-manager state, shown only when activation hits the cap error.
  const [seatCap, setSeatCap] = useState<{ cap: number; tier: string } | null>(null);
  const [seats, setSeats] = useState<ActivationsResponse | null>(null);
  const [seatsLoading, setSeatsLoading] = useState(false);
  const [freeingMachine, setFreeingMachine] = useState<string | null>(null);

  const loadSeats = async (pastedKey: string) => {
    setSeatsLoading(true);
    try {
      const res = await license.listActivationsByKey(pastedKey);
      setSeats(res);
    } catch (err: any) {
      setError(`Could not load seat list: ${err?.detail ?? err?.message ?? 'unknown'}`);
    } finally {
      setSeatsLoading(false);
    }
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await license.activate(key.trim());
      onActivated();
    } catch (err: any) {
      const raw = err?.detailRaw;
      if (raw && typeof raw === 'object' && raw.error === 'seat_cap_exceeded') {
        setSeatCap({ cap: Number(raw.cap) || 0, tier: String(raw.tier ?? '') });
        setError(
          `All ${raw.cap} machine seats on your ${raw.tier} tier are already in use. ` +
            'Deactivate one of the machines below, then click Activate again.',
        );
        await loadSeats(key.trim());
      } else if (typeof err?.detail === 'string') {
        setError(err.detail);
      } else if (err?.message) {
        setError(err.message);
      } else {
        setError('Activation failed.');
      }
    } finally {
      setSubmitting(false);
    }
  };

  const onFreeSeat = async (targetMachineId: string) => {
    if (
      !confirm(
        `Free the seat held by machine ${targetMachineId.slice(0, 8)}...? That install will lock on its next heartbeat.`,
      )
    ) {
      return;
    }
    setFreeingMachine(targetMachineId);
    try {
      const res = await license.freeSeatByKey(key.trim(), targetMachineId);
      setSeats(res);
    } catch (err: any) {
      const raw = err?.detailRaw;
      const reason =
        (raw && typeof raw === 'object' && (raw.reason || raw.error)) ||
        err?.detail ||
        err?.message ||
        'unknown';
      setError(`Could not deactivate: ${reason}`);
    } finally {
      setFreeingMachine(null);
    }
  };

  const heading =
    status === 'expired'
      ? 'Your license has expired'
      : status === 'invalid'
      ? 'License signature invalid'
      : 'Activate Creator Studio';
  const sub =
    status === 'expired'
      ? 'Renew to keep generating and to receive future updates. Paste your new license key below.'
      : status === 'invalid'
      ? 'The stored license did not verify against the embedded public key. Paste a fresh key from your order email.'
      : 'Paste the license key from your order email to unlock the app. Keys are signed and verified locally — no internet roundtrip needed.';

  return (
    <div className="min-h-screen flex items-center justify-center bg-bg-base p-6">
      <div className="w-full max-w-lg bg-bg-elevated/80 backdrop-blur-sm border border-white/[0.06] rounded-lg p-8 shadow-lg">
        <h1 className="text-2xl font-semibold text-txt-primary mb-2">{heading}</h1>
        <p className="text-sm text-txt-secondary mb-6">{sub}</p>{seatCap ? (
          <div className="mb-4 p-4 rounded border border-amber-500/30 bg-amber-500/5">
            <div className="flex items-center gap-2 mb-2">
              <Monitor size={14} className="text-amber-400" />
              <span className="text-xs font-semibold text-amber-200">
                Seat cap: {seats?.activations.length ?? seatCap.cap} / {seatCap.cap} used on{' '}
                {seatCap.tier}
              </span>
            </div>
            <p className="text-xs text-txt-secondary mb-3">
              Free a seat below, then click Activate again. The other install will lock on its
              next heartbeat (within 24 hours).
            </p>
            {seatsLoading && !seats && (
              <div className="text-xs text-txt-muted">Loading seat list...</div>
            )}
            {seats && seats.activations.length === 0 && (
              <div className="text-xs text-txt-muted">No machines currently registered.</div>
            )}
            <div className="space-y-2">
              {seats?.activations.map((a) => (
                <div
                  key={a.machine_id}
                  className="flex items-center justify-between gap-3 p-2 rounded bg-bg-base/50"
                >
                  <div className="min-w-0">
                    <code className="text-[11px] font-mono text-txt-primary truncate block">
                      {a.machine_id}
                    </code>
                    <div className="text-[10px] text-txt-muted">
                      {a.last_known_version && (
                        <span className="mr-2">v{a.last_known_version}</span>
                      )}
                      last heartbeat{' '}
                      {a.last_heartbeat
                        ? new Date(
                            (a.last_heartbeat < 1e12 ? a.last_heartbeat * 1000 : a.last_heartbeat),
                          ).toLocaleString()
                        : 'unknown'}
                    </div>
                  </div>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => onFreeSeat(a.machine_id)}
                    disabled={freeingMachine === a.machine_id}
                    className="shrink-0 text-error hover:bg-error/10"
                  >
                    <Trash2 size={12} />
                    {freeingMachine === a.machine_id ? '...' : 'Free seat'}
                  </Button>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {stateError && (
          <div className="mb-4 p-3 rounded border border-error/30 bg-error/10 text-xs text-error">
            {stateError}
          </div>
        )}

        <form onSubmit={onSubmit} className="space-y-4">
          <div>
            <label htmlFor="license-key" className="block text-xs text-txt-secondary mb-1">
              License key (JWT)
            </label>
            <textarea
              id="license-key"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              className="w-full h-28 px-3 py-2 bg-bg-base border border-white/[0.08] rounded-md text-xs font-mono text-txt-primary focus:outline-none focus:border-accent/40 resize-none"
              placeholder="eyJhbGciOiJFZERTQSI..."
              spellCheck={false}
              autoComplete="off"
              required
            />
          </div>

          {error && (
            <div className="p-3 rounded border border-error/30 bg-error/10 text-xs text-error">
              {error}
            </div>
          )}

          <div className="flex items-center justify-between gap-3">
            <div className="text-xs text-txt-secondary">
              {machineId && <span>Machine ID: <code className="font-mono">{machineId}</code></span>}
            </div>
            <Button type="submit" variant="primary" size="md" disabled={submitting || !key.trim()}>
              {submitting ? 'Activating…' : 'Activate'}
            </Button>
          </div>
        </form>

        <div className="mt-6 pt-4 border-t border-white/[0.06] text-xs text-txt-secondary">
          <p>
            Need a key? Buy a subscription at{' '}
            <a
              href="https://drevalis.com"
              target="_blank"
              rel="noreferrer"
              className="text-accent hover:underline"
            >
              drevalis.com
            </a>
            .
          </p>
        </div>
      </div>
    </div>
  );
}

export default ActivationWizard;
