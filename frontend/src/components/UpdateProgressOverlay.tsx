import { useEffect, useRef, useState } from 'react';
import { CheckCircle2, XCircle, Loader2, ArrowUpCircle, Download, RefreshCw, Heart } from 'lucide-react';
import type { UpdateProgress } from '@/lib/api';

/**
 * Full-screen overlay shown during an in-app update.
 *
 * The update runs in a sidecar that recycles every service in the stack
 * — the app container that served this page will restart, as will the
 * frontend container. The browser tab keeps the JS alive across that
 * window; we poll two endpoints:
 *
 *   1. GET /api/v1/updates/progress  -- phase markers written by the
 *      updater to /shared/update_status.json. Goes unreachable while
 *      the app is being recreated (that gap IS a progress signal).
 *   2. GET /health                   -- comes back online once the new
 *      app container is healthy.
 *
 * When we see phase=done AND /health 200 again, we auto-reload the
 * browser to pick up the new frontend bundle. On phase=failed we show
 * the error and offer a "Reload anyway" button.
 */

type Step = {
  key: string;
  label: string;
  hint: string;
  icon: typeof Download;
};

const STEPS: Step[] = [
  { key: 'pulling', label: 'Pulling new images', hint: 'Downloading from GHCR', icon: Download },
  { key: 'pulled', label: 'Images pulled', hint: 'Handing off to docker compose', icon: CheckCircle2 },
  { key: 'restarting', label: 'Restarting services', hint: 'Old containers stop, new ones start', icon: RefreshCw },
  { key: 'waiting', label: 'Waiting for health check', hint: 'New app container coming online', icon: Heart },
  { key: 'done', label: 'Complete', hint: 'Reloading to the new version', icon: CheckCircle2 },
];

const STEP_ORDER = ['pulling', 'pulled', 'restarting', 'waiting', 'done'];

interface Props {
  open: boolean;
  onClose: () => void;
}

export function UpdateProgressOverlay({ open, onClose }: Props) {
  const [progress, setProgress] = useState<UpdateProgress | null>(null);
  const [unreachable, setUnreachable] = useState(false);
  const [healthOk, setHealthOk] = useState(false);
  const [startedAt] = useState<Date>(new Date());
  const [, tick] = useState(0);
  const pollTimer = useRef<number | null>(null);

  // Elapsed-seconds tick for the on-screen clock.
  useEffect(() => {
    if (!open) return;
    const id = window.setInterval(() => tick((t) => t + 1), 1000);
    return () => window.clearInterval(id);
  }, [open]);

  // Poll progress + health continuously while the overlay is open.
  useEffect(() => {
    if (!open) return;

    let cancelled = false;

    const poll = async () => {
      // /api/v1/updates/progress
      try {
        const res = await fetch('/api/v1/updates/progress', { cache: 'no-store' });
        if (cancelled) return;
        if (res.ok) {
          const data = (await res.json()) as UpdateProgress;
          setProgress(data);
          setUnreachable(false);
        } else {
          setUnreachable(true);
        }
      } catch {
        if (!cancelled) setUnreachable(true);
      }

      // /health — survives as long as nginx proxy has any upstream.
      try {
        const res = await fetch('/health', { cache: 'no-store' });
        if (!cancelled) setHealthOk(res.ok);
      } catch {
        if (!cancelled) setHealthOk(false);
      }
    };

    void poll();
    pollTimer.current = window.setInterval(poll, 1500);
    return () => {
      cancelled = true;
      if (pollTimer.current) window.clearInterval(pollTimer.current);
    };
  }, [open]);

  // Auto-reload once the new stack is alive.
  useEffect(() => {
    if (!open) return;
    if (progress?.phase === 'done' && healthOk) {
      const t = window.setTimeout(() => window.location.reload(), 2000);
      return () => window.clearTimeout(t);
    }
    return undefined;
  }, [open, progress?.phase, healthOk]);

  if (!open) return null;

  // Which logical step are we on?
  // "waiting" is virtual — it's whenever the progress endpoint is
  // unreachable OR the stack is back to pulling-out-of-healthcheck.
  let currentStep: string = progress?.phase ?? 'pulling';
  if (progress?.phase === 'restarting' && unreachable) {
    currentStep = 'waiting';
  } else if (unreachable && progress === null) {
    currentStep = 'waiting';
  } else if (progress?.phase === 'done' && !healthOk) {
    currentStep = 'waiting';
  }

  const failed = progress?.phase === 'failed';
  const complete = progress?.phase === 'done' && healthOk;

  const activeIdx = STEP_ORDER.indexOf(currentStep);
  const elapsed = Math.max(0, Math.floor((Date.now() - startedAt.getTime()) / 1000));

  return (
    <div
      className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/80 backdrop-blur-md"
      role="dialog"
      aria-modal="true"
      aria-labelledby="update-overlay-title"
    >
      <div className="w-full max-w-lg bg-bg-surface border border-white/[0.06] rounded-xl shadow-2xl p-8">
        <div className="flex items-start gap-3 mb-6">
          <ArrowUpCircle className="text-accent shrink-0" size={26} />
          <div>
            <h2 id="update-overlay-title" className="text-xl font-semibold">
              {failed ? 'Update failed' : complete ? 'Update complete' : 'Updating Drevalis Creator Studio'}
            </h2>
            <p className="text-sm text-txt-secondary mt-1">
              {failed
                ? progress?.detail || 'See updater container logs for details.'
                : complete
                ? 'Reloading in 2 seconds to pick up the new version...'
                : 'Do not close this tab. The app will be unavailable for ~60 seconds.'}
            </p>
          </div>
        </div>

        {/* Step list */}
        <ol className="space-y-3 mb-6">
          {STEPS.map((step, i) => {
            const done = !failed && (complete || i < activeIdx);
            const active = !failed && i === activeIdx;
            const Icon = step.icon;
            return (
              <li
                key={step.key}
                className={[
                  'flex items-start gap-3 p-3 rounded border',
                  done
                    ? 'border-accent/30 bg-accent/[0.04]'
                    : active
                    ? 'border-accent/40 bg-accent/10'
                    : 'border-white/[0.06] bg-bg-elevated/50',
                ].join(' ')}
              >
                <div className="shrink-0 mt-0.5">
                  {done ? (
                    <CheckCircle2 size={18} className="text-accent" />
                  ) : active ? (
                    <Loader2 size={18} className="text-accent animate-spin" />
                  ) : (
                    <Icon size={18} className="text-txt-muted" />
                  )}
                </div>
                <div className="min-w-0">
                  <div className={['text-sm', done || active ? 'text-txt-primary font-medium' : 'text-txt-muted'].join(' ')}>
                    {step.label}
                  </div>
                  <div className="text-xs text-txt-muted mt-0.5">{step.hint}</div>
                </div>
              </li>
            );
          })}
        </ol>

        {/* Failure state */}
        {failed && (
          <div className="rounded border border-error/30 bg-error/10 p-3 mb-4 text-xs text-error flex items-start gap-2">
            <XCircle size={14} className="shrink-0 mt-0.5" />
            <div>
              <div className="font-semibold">Update aborted</div>
              <div className="mt-0.5 text-error/80 break-words">
                {progress?.detail || 'Unknown error'}
              </div>
            </div>
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between text-xs text-txt-muted">
          <span>Elapsed: {elapsed}s</span>
          {(failed || complete) && (
            <div className="flex gap-2">
              {failed && (
                <button
                  onClick={() => window.location.reload()}
                  className="px-3 py-1.5 rounded bg-bg-elevated text-txt-primary hover:bg-bg-hover"
                >
                  Reload anyway
                </button>
              )}
              <button
                onClick={onClose}
                className="px-3 py-1.5 rounded bg-bg-elevated text-txt-primary hover:bg-bg-hover"
              >
                Close
              </button>
            </div>
          )}
        </div>

        {/* Diagnostic strip */}
        <div className="mt-4 pt-3 border-t border-white/[0.06] text-[11px] text-txt-muted font-mono">
          <div>
            progress endpoint: {unreachable ? 'unreachable (expected mid-restart)' : 'reachable'}
          </div>
          <div>/health: {healthOk ? 'OK' : 'down (expected mid-restart)'}</div>
          <div>phase: {progress?.phase ?? 'waiting-for-first-response'}</div>
        </div>
      </div>
    </div>
  );
}
