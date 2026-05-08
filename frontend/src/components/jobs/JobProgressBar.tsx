import { useEffect, useRef } from 'react';
import type { PipelineStep, ProgressMessage } from '@/types';
import { useNow } from '@/lib/use-now';
import { STEP_BG, STEP_MUTED, STEP_ORDER } from '@/lib/stepColors';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

// Step ordering + labels for THIS bar. Colours come from
// ``lib/stepColors.ts`` so a theme-preset switch (cyber / warm /
// brutalist) automatically restyles every step badge in the app.
const PIPELINE_STEPS: readonly PipelineStep[] = STEP_ORDER;

const STEP_LABELS: Record<PipelineStep, string> = {
  script: 'Script',
  voice: 'Voice',
  scenes: 'Scenes',
  captions: 'Captions',
  assembly: 'Assembly',
  thumbnail: 'Thumbnail',
};

/** Stale threshold in ms -- if progress hasn't changed for this long, show pulse */
const STALE_THRESHOLD_MS = 5000;

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface JobProgressBarProps {
  /** Latest progress for each step, keyed by step name */
  stepProgress: Record<string, ProgressMessage>;
  compact?: boolean;
  className?: string;
  /** ISO timestamp when the current active step started (for elapsed time) */
  startedAt?: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatElapsed(startedAt: string): string {
  const elapsed = Math.floor(
    (Date.now() - new Date(startedAt).getTime()) / 1000,
  );
  if (elapsed < 0) return '';
  const min = Math.floor(elapsed / 60);
  const sec = elapsed % 60;
  return `${min}m ${sec.toString().padStart(2, '0')}s`;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

function JobProgressBar({
  stepProgress,
  compact = false,
  className = '',
  startedAt,
}: JobProgressBarProps) {
  // Track when progress last changed to detect "stale" / waiting states
  const lastProgressRef = useRef<string>('');
  const lastChangeRef = useRef<number>(Date.now());

  // Single shared 1-Hz tick rather than a per-instance setInterval.
  // The Activity Monitor renders ~8 of these at once; collapsing the
  // timers from N → 1 cuts the per-second React reconciliation work.
  const now = useNow(1000);
  const isStale = now - lastChangeRef.current > STALE_THRESHOLD_MS;

  // Serialize current progress for change detection
  const progressKey = JSON.stringify(
    Object.entries(stepProgress).map(([k, v]) => [k, v.progress_pct, v.status]),
  );

  useEffect(() => {
    if (progressKey !== lastProgressRef.current) {
      lastProgressRef.current = progressKey;
      lastChangeRef.current = Date.now();
    }
  }, [progressKey]);

  // Determine overall progress
  const totalSteps = PIPELINE_STEPS.length;
  let completedSteps = 0;
  let activeStepIdx = -1;
  let overallPct = 0;

  PIPELINE_STEPS.forEach((step, idx) => {
    const msg = stepProgress[step];
    if (!msg) return;
    if (msg.status === 'done') {
      completedSteps++;
      overallPct += 100;
    } else if (msg.status === 'running') {
      activeStepIdx = idx;
      overallPct += msg.progress_pct;
    } else if (msg.status === 'failed') {
      activeStepIdx = idx;
      overallPct += msg.progress_pct;
    }
  });

  const overallPercent = Math.round(overallPct / totalSteps);

  // Active step info
  const activeStep =
    activeStepIdx >= 0 ? PIPELINE_STEPS[activeStepIdx] : null;
  const activeMsg = activeStep ? stepProgress[activeStep] : null;

  // Pulse class when stale and a step is running
  const pulseClass =
    isStale && activeMsg?.status === 'running' ? 'animate-pulse' : '';

  if (compact) {
    return (
      <div className={`flex items-center gap-2 ${className}`}>
        {/* Mini bar */}
        <div
          className={`flex-1 h-1.5 bg-bg-hover rounded-full overflow-hidden flex ${pulseClass}`}
        >
          {PIPELINE_STEPS.map((step) => {
            const msg = stepProgress[step];
            const isDone = msg?.status === 'done';
            const isRunning = msg?.status === 'running';
            const isFailed = msg?.status === 'failed';
            const pct = msg?.progress_pct ?? 0;

            return (
              <div
                key={step}
                className={`flex-1 relative ${STEP_MUTED[step]}`}
              >
                <div
                  className={[
                    'absolute inset-y-0 left-0 transition-all duration-slow',
                    isRunning ? 'progress-stripe' : '',
                    isFailed ? 'bg-error' : STEP_BG[step],
                  ].join(' ')}
                  style={{ width: isDone ? '100%' : `${pct}%` }}
                />
              </div>
            );
          })}
        </div>
        <span className="text-xs text-txt-secondary font-mono tabular-nums shrink-0">
          {overallPercent}%
        </span>
      </div>
    );
  }

  return (
    <div className={className}>
      {/* Step segments */}
      <div
        className={`flex gap-0.5 h-2 rounded overflow-hidden ${pulseClass}`}
      >
        {PIPELINE_STEPS.map((step) => {
          const msg = stepProgress[step];
          const isDone = msg?.status === 'done';
          const isRunning = msg?.status === 'running';
          const isFailed = msg?.status === 'failed';
          const pct = msg?.progress_pct ?? 0;

          return (
            <div
              key={step}
              className={`flex-1 relative rounded-sm overflow-hidden ${STEP_MUTED[step]}`}
              title={`${STEP_LABELS[step]}: ${isDone ? '100' : pct}%`}
            >
              <div
                className={[
                  'absolute inset-y-0 left-0 rounded-sm transition-all duration-slow',
                  isRunning ? 'progress-stripe' : '',
                  isFailed ? 'bg-error' : STEP_BG[step],
                ].join(' ')}
                style={{ width: isDone ? '100%' : `${pct}%` }}
              />
            </div>
          );
        })}
      </div>

      {/* Step labels with elapsed time on active step */}
      <div className="flex gap-0.5 mt-1">
        {PIPELINE_STEPS.map((step, idx) => {
          const msg = stepProgress[step];
          const isActive = idx === activeStepIdx;
          const isDone = msg?.status === 'done';
          const isFailed = msg?.status === 'failed';

          return (
            <div key={step} className="flex-1 text-center">
              <span
                className={[
                  'text-xs',
                  isActive
                    ? 'text-txt-primary font-medium'
                    : isDone
                      ? 'text-txt-secondary'
                      : isFailed
                        ? 'text-error'
                        : 'text-txt-tertiary',
                ].join(' ')}
              >
                {STEP_LABELS[step]}
                {isActive && startedAt && (
                  <span className="text-txt-tertiary font-normal ml-1">
                    {formatElapsed(startedAt)}
                  </span>
                )}
              </span>
            </div>
          );
        })}
      </div>

      {/* Active step message + sub-step info */}
      {activeMsg && activeStep && (
        <div className="mt-2 flex items-center justify-between">
          <div className="flex-1 min-w-0">
            <span className="text-xs text-txt-secondary">
              {activeMsg.message ||
                `${STEP_LABELS[activeStep]} in progress...`}
            </span>
            {/* Sub-step detail from progress message detail field */}
            {activeMsg.detail &&
              typeof activeMsg.detail === 'object' &&
              'sub_step' in activeMsg.detail && (
                <span className="text-[10px] text-txt-tertiary ml-2">
                  {String((activeMsg.detail as Record<string, unknown>).sub_step)}
                </span>
              )}
            {isStale && activeMsg.status === 'running' && (
              <span className="text-[10px] text-txt-tertiary ml-2">
                (waiting...)
              </span>
            )}
          </div>
          <span className="text-xs text-txt-primary font-mono tabular-nums shrink-0 ml-2">
            {overallPercent}%
          </span>
        </div>
      )}
      {/* Screen-reader announcement — fires only on step transitions, not
          every percentage tick, so SRs aren't flooded with chatter. */}
      <span className="sr-only" aria-live="polite">
        {activeStep
          ? `${STEP_LABELS[activeStep]} step in progress`
          : completedSteps === totalSteps && totalSteps > 0
            ? 'Generation complete'
            : ''}
      </span>
    </div>
  );
}

export { JobProgressBar, PIPELINE_STEPS, STEP_LABELS };
export type { JobProgressBarProps };
