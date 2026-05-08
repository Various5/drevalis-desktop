/**
 * JobCard — one card per active background task.
 *
 * Three-row layout:
 *   Row 1: [icon + title (truncate)]  [step badge]
 *   Row 2: progress bar
 *   Row 3: elapsed time               [cancel button (icon only, ghost)]
 *
 * Cancel is surfaced as a plain icon button — no overflow menu needed
 * because there are no other per-card actions in this design iteration.
 */

import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Play, Mic, Sparkles, Square } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { Spinner } from '@/components/ui/Spinner';
import { Tooltip } from '@/components/ui/Tooltip';
import { STEP_BG, STEP_TEXT, isKnownStep, type StepName } from '@/lib/stepColors';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface BackgroundTask {
  type: 'episode_generation' | 'audiobook_generation' | 'script_generation';
  id: string;
  title: string;
  step: string;
  status: string;
  progress: number; // -1 = indeterminate
  url: string;
}

interface JobCardProps {
  task: BackgroundTask;
  cancelling: boolean;
  onCancel: (task: BackgroundTask) => void;
}

// ---------------------------------------------------------------------------
// Step colour helpers (alias tts → voice, llm → script)
// ---------------------------------------------------------------------------

const STEP_ALIASES: Record<string, StepName> = {
  tts: 'voice',
  llm: 'script',
};

function stepBg(step: string): string {
  if (isKnownStep(step)) return STEP_BG[step];
  const aliased = STEP_ALIASES[step];
  return aliased ? STEP_BG[aliased] : 'bg-accent';
}

function stepText(step: string): string {
  if (isKnownStep(step)) return STEP_TEXT[step];
  const aliased = STEP_ALIASES[step];
  return aliased ? STEP_TEXT[aliased] : 'text-txt-secondary';
}

// ---------------------------------------------------------------------------
// Task icons
// ---------------------------------------------------------------------------

const TASK_ICONS: Record<BackgroundTask['type'], typeof Play> = {
  episode_generation: Play,
  audiobook_generation: Mic,
  script_generation: Sparkles,
};

// ---------------------------------------------------------------------------
// Elapsed-time hook
// ---------------------------------------------------------------------------

function useElapsedSeconds(startedAt: number): number {
  const [elapsed, setElapsed] = useState(() =>
    Math.floor((Date.now() - startedAt) / 1000),
  );
  useEffect(() => {
    const id = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);
    return () => clearInterval(id);
  }, [startedAt]);
  return elapsed;
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return s > 0 ? `${m}m ${s}s` : `${m}m`;
}

// ---------------------------------------------------------------------------
// JobCard
// ---------------------------------------------------------------------------

export function JobCard({ task, cancelling, onCancel }: JobCardProps) {
  const navigate = useNavigate();
  const mountedAt = useRef(Date.now()).current;
  const elapsed = useElapsedSeconds(mountedAt);
  const isIndeterminate = task.progress < 0;
  const Icon = TASK_ICONS[task.type] ?? Play;

  return (
    <div
      className="bg-bg-elevated/40 border border-white/[0.05] rounded-lg px-3 py-2.5 flex flex-col gap-2"
      data-testid={`job-card-${task.id}`}
    >
      {/* ── Row 1: title + step badge ──────────────────────────────── */}
      <div className="flex items-center gap-2 min-w-0">
        <Icon
          size={11}
          className="text-accent flex-shrink-0"
          aria-hidden="true"
        />
        <button
          onClick={() => navigate(task.url)}
          className="text-xs font-medium text-txt-primary hover:text-accent truncate text-left flex-1 min-w-0 focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2 rounded-sm"
          aria-label={`Open ${task.title}`}
        >
          {task.title}
        </button>
        <Badge
          variant={task.step}
          className={`text-[9px] flex-shrink-0 px-1.5 py-0.5 ${stepText(task.step)}`}
        >
          {task.step}
        </Badge>
      </div>

      {/* ── Row 2: progress bar ────────────────────────────────────── */}
      <div
        className="h-1 bg-bg-surface rounded-full overflow-hidden"
        role="progressbar"
        aria-valuenow={isIndeterminate ? undefined : task.progress}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`${task.title} progress`}
      >
        {isIndeterminate ? (
          <div
            className={`h-full w-1/2 rounded-full animate-pulse ${stepBg(task.step)}`}
          />
        ) : (
          <div
            className={`h-full rounded-full transition-all duration-500 ${stepBg(task.step)}`}
            style={{ width: `${task.progress}%` }}
          />
        )}
      </div>

      {/* ── Row 3: elapsed + cancel ────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-txt-tertiary">
          {isIndeterminate ? (
            <span className="flex items-center gap-1">
              <Spinner size="sm" />
              {formatDuration(elapsed)}
            </span>
          ) : (
            `${task.progress}% · ${formatDuration(elapsed)}`
          )}
        </span>

        {task.type === 'episode_generation' && (
          <Tooltip content={`Cancel ${task.title}`} side="left">
            <button
              onClick={() => onCancel(task)}
              disabled={cancelling}
              className="text-txt-tertiary hover:text-red-400 transition-colors disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2 rounded-sm p-0.5"
              aria-label={`Cancel ${task.title}`}
            >
              <Square size={11} />
            </button>
          </Tooltip>
        )}
      </div>
    </div>
  );
}
