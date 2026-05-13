import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Activity, ChevronRight, CheckCircle2 } from 'lucide-react';
import { useActiveJobs } from '@/lib/queries/jobs';
import { useActiveJobsProgress } from '@/lib/websocket';
import { JobProgressBar } from '@/components/jobs/JobProgressBar';
import type { GenerationJobListItem, ProgressMessage } from '@/types';

// ---------------------------------------------------------------------------
// ActiveJobsPopover — header-pill that opens a dropdown listing every
// running generation job across workers (the "what's running" panel).
// ---------------------------------------------------------------------------
//
// Data sources:
//   * ``useActiveJobs()`` for the persisted job rows (correct on first
//     paint).
//   * ``useActiveJobsProgress()`` for the WebSocket-pushed progress
//     events (correct in real time).
// They're merged the same way ActiveJobsWidget does it — WS overrides
// the API snapshot per step.

function mergeProgress(
  jobs: GenerationJobListItem[],
  wsProgress: Record<string, ProgressMessage>,
): Record<string, ProgressMessage> {
  const apiProgress: Record<string, ProgressMessage> = {};
  for (const job of jobs) {
    apiProgress[job.step] = {
      status: job.status,
      progress_pct: job.progress_pct,
      message: job.error_message ?? '',
    } as ProgressMessage;
  }
  return { ...apiProgress, ...wsProgress };
}

export function ActiveJobsPopover() {
  const { latestByEpisode } = useActiveJobsProgress();
  const hasActive = Object.keys(latestByEpisode).length > 0;
  const { data: activeJobs = [] } = useActiveJobs({ hasActive });
  const count = activeJobs.length;

  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onClick);
    document.addEventListener('keydown', onEsc);
    return () => {
      document.removeEventListener('mousedown', onClick);
      document.removeEventListener('keydown', onEsc);
    };
  }, [open]);

  // Group jobs by episode so the panel reads as "what's currently
  // generating" rather than a flat per-step row dump.
  const jobsByEpisode = activeJobs.reduce<Record<string, GenerationJobListItem[]>>(
    (acc, job) => {
      const key = job.episode_id;
      (acc[key] ||= []).push(job);
      return acc;
    },
    {},
  );

  if (count === 0) return null;

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-full text-accent bg-accent/[0.08] border border-accent/20 hover:bg-accent/[0.12] transition-all duration-normal"
        aria-haspopup="dialog"
        aria-expanded={open}
        title="What's running"
      >
        <Activity size={14} className="animate-pulse" />
        <span className="text-xs font-medium">{count}</span>
        <span className="text-xs text-accent/70">{count === 1 ? 'job' : 'jobs'}</span>
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Active generation jobs"
          className="absolute right-0 top-full mt-1.5 w-[min(420px,90vw)] rounded-md border border-white/[0.06] bg-bg-elevated shadow-xl z-dropdown overflow-hidden"
        >
          <header className="flex items-center justify-between px-3 py-2 border-b border-white/[0.04]">
            <span className="text-xs font-display font-semibold text-txt-tertiary uppercase tracking-[0.15em]">
              Running now ({count})
            </span>
            <Link
              to="/"
              onClick={() => setOpen(false)}
              className="text-xs text-accent hover:underline inline-flex items-center gap-0.5"
            >
              View all <ChevronRight size={12} />
            </Link>
          </header>
          <div className="max-h-[60vh] overflow-y-auto divide-y divide-white/[0.04]">
            {Object.keys(jobsByEpisode).length === 0 ? (
              <div className="px-4 py-6 text-center">
                <CheckCircle2 size={20} className="text-txt-tertiary mx-auto mb-1.5" />
                <p className="text-xs text-txt-secondary">No active jobs</p>
              </div>
            ) : (
              Object.entries(jobsByEpisode).map(([episodeId, epJobs]) => {
                const merged = mergeProgress(epJobs, latestByEpisode[episodeId] ?? {});
                return (
                  <Link
                    key={episodeId}
                    to={`/episodes/${episodeId}`}
                    onClick={() => setOpen(false)}
                    className="block px-3 py-2.5 hover:bg-white/[0.04] transition-colors"
                  >
                    <div className="flex items-center justify-between mb-1.5">
                      <span className="text-xs font-medium text-txt-primary truncate">
                        Episode {episodeId.slice(0, 8)}…
                      </span>
                      <span className="text-[10px] text-txt-tertiary">
                        {epJobs.length} step{epJobs.length === 1 ? '' : 's'}
                      </span>
                    </div>
                    <JobProgressBar stepProgress={merged} compact />
                  </Link>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}
