/**
 * ActivityMonitor — docked activity rail.
 *
 * Dock position is controlled by ``activityDock`` from the theme context:
 *   bottom / top → horizontal tray (default collapsed)
 *   left / right → vertical rail (40 px collapsed, 320 px expanded)
 *
 * Visual hierarchy (expanded state):
 *   1. HeaderStrip  — worker status + slots + priority selector (~32 px)
 *   2. Job cards    — one card per active job, scrollable
 *   3. BulkActions  — Pause / Cancel / Retry-failed (shown when relevant)
 *
 * Mobile: floating pill at bottom-right; tapping navigates to /jobs.
 *
 * ALL behavior (handlers, priority flag, cancel/retry/pause calls) is
 * preserved unchanged from v0.30.x — only layout and classes changed.
 */

import { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { Activity, ChevronUp, ChevronDown } from 'lucide-react';
import { Spinner } from '@/components/ui/Spinner';
import { useToast } from '@/components/ui/Toast';
import { jobs as jobsApi, episodes as episodesApi } from '@/lib/api';
import { useActiveJobsProgress } from '@/lib/websocket';
import { useTheme } from '@/lib/theme';
import { useActiveTasks, useJobsStatus, useWorkerHealth, queryKeys } from '@/lib/queries';
import { useQueryClient } from '@tanstack/react-query';

import { HeaderStrip, type PriorityMode } from './HeaderStrip';
import { JobCard, type BackgroundTask } from './JobCard';
import { BulkActions } from './BulkActions';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface QueueStatus {
  active: number;
  queued: number;
  max_concurrent: number;
  slots_available: number;
  total_failed_episodes: number;
}

interface WorkerHealth {
  alive: boolean;
  last_heartbeat: string | null;
  generating_count: number;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PRIORITY_STORAGE_KEY = 'sf_job_priority';

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ActivityMonitor() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const { activityDock } = useTheme();
  const isVerticalDock = activityDock === 'left' || activityDock === 'right';

  const [userExpanded, setUserExpanded] = useState(false);
  const expanded = userExpanded;
  const setExpanded = (v: boolean) => setUserExpanded(v);

  const [cancelling, setCancelling] = useState<Set<string>>(new Set());
  const [restartingWorker, setRestartingWorker] = useState(false);
  const [priority, setPriority] = useState<PriorityMode>(() => {
    const stored = localStorage.getItem(PRIORITY_STORAGE_KEY);
    return (stored as PriorityMode | null) ?? 'shorts_first';
  });

  const { latestByEpisode, connected: wsConnected } = useActiveJobsProgress();

  const hasActive = Object.keys(latestByEpisode).length > 0;
  const tasksQ = useActiveTasks({ hasActive });
  const statusQ = useJobsStatus({ hasActive });
  const workerHealthQ = useWorkerHealth();
  const qc = useQueryClient();

  // Merge API task list with fresher WS progress data
  const tasks: BackgroundTask[] = useMemo(() => {
    const apiTasks = tasksQ.data?.tasks ?? [];
    return apiTasks.map(
      (t: {
        type?: string;
        id: string;
        title?: string;
        step?: string;
        status?: string;
        progress?: number;
        url?: string;
      }) => {
        const ws = latestByEpisode[t.id];
        const wsProgress = ws
          ? Object.values(ws).reduce(
              (best, msg) =>
                msg.progress_pct > (best?.progress_pct ?? -1) ? msg : best,
              Object.values(ws)[0],
            )
          : null;
        return {
          type: (t.type as BackgroundTask['type']) ?? 'episode_generation',
          id: t.id,
          title: t.title ?? 'Untitled',
          step: wsProgress?.step ?? t.step ?? 'script',
          status: t.status ?? 'running',
          progress: wsProgress?.progress_pct ?? t.progress ?? -1,
          url: t.url ?? `/episodes/${t.id}`,
        };
      },
    );
  }, [tasksQ.data, latestByEpisode]);

  const queueStatus: QueueStatus | null = useMemo(() => {
    const s = statusQ.data;
    if (!s) return null;
    return {
      active: s.generating_episodes ?? 0,
      queued: s.queued ?? 0,
      max_concurrent: s.max_concurrent ?? 4,
      slots_available: s.slots_available ?? 0,
      total_failed_episodes: s.total_failed_episodes ?? 0,
    };
  }, [statusQ.data]);

  const workerHealth: WorkerHealth | null = workerHealthQ.data
    ? workerHealthQ.data
    : workerHealthQ.isError
      ? { alive: false, last_heartbeat: null, generating_count: 0 }
      : null;

  const refetchAll = () => {
    void qc.invalidateQueries({ queryKey: queryKeys.jobs.all });
  };

  // Load priority from backend on mount
  useEffect(() => {
    jobsApi
      .getPriority()
      .then((d) => {
        const mode = d.mode as PriorityMode;
        if (['shorts_first', 'longform_first', 'fifo'].includes(mode)) {
          setPriority(mode);
          localStorage.setItem(PRIORITY_STORAGE_KEY, mode);
        }
      })
      .catch(() => {});
  }, []);

  // ── Handlers ─────────────────────────────────────────────────────

  const handleCancel = async (task: BackgroundTask) => {
    setCancelling((prev) => new Set(prev).add(task.id));
    try {
      if (task.type === 'episode_generation') await episodesApi.cancel(task.id);
      toast.success('Job cancelled');
    } catch (err) {
      toast.error('Failed to cancel job', { description: String(err) });
    } finally {
      setCancelling((prev) => {
        const n = new Set(prev);
        n.delete(task.id);
        return n;
      });
    }
  };

  const handleRestartWorker = async () => {
    setRestartingWorker(true);
    try {
      await jobsApi.restartWorker();
      toast.info('Worker restart signal sent');
      setTimeout(() => {
        refetchAll();
      }, 3000);
    } catch (err) {
      toast.error('Failed to restart worker', { description: String(err) });
    } finally {
      setRestartingWorker(false);
    }
  };

  const handlePriorityChange = (next: PriorityMode) => {
    setPriority(next);
    localStorage.setItem(PRIORITY_STORAGE_KEY, next);
    void jobsApi.setPriority(next);
  };

  const handlePauseAll = () => {
    jobsApi
      .pauseAll()
      .then(() => toast.info('Queue paused'))
      .catch((e) => toast.error('Pause failed', { description: String(e) }));
  };

  const handleCancelAll = () => {
    jobsApi
      .cancelAll()
      .then(() => toast.warning('All jobs cancelled'))
      .catch((e) => toast.error('Cancel failed', { description: String(e) }));
  };

  const handleRetryFailed = () => {
    jobsApi
      .retryAllFailed()
      .then(() => toast.success(`Retrying ${failedCount} failed jobs`))
      .catch((e) => toast.error('Retry failed', { description: String(e) }));
  };

  const handleCleanup = () => {
    jobsApi
      .cleanup()
      .then(() => toast.success('Cleanup complete'))
      .catch((e) => toast.error('Cleanup failed', { description: String(e) }));
  };

  // ── Derived values ───────────────────────────────────────────────

  const totalActive = tasks.length;
  const failedCount = queueStatus?.total_failed_episodes ?? 0;

  // ── Render: collapsed vertical rail ─────────────────────────────

  if (isVerticalDock && !expanded) {
    return (
      <>
        {/* Mobile pill */}
        <MobilePill totalActive={totalActive} navigate={navigate} />

        {/* Collapsed vertical rail */}
        <div
          className={[
            'hidden md:flex fixed z-40 flex-col items-center py-3 gap-3',
            'bg-bg-surface/90 backdrop-blur-xl border-white/[0.08]',
            'shadow-[0_8px_32px_-8px_rgba(0,0,0,0.55)]',
            'w-[44px] top-0 bottom-0 transition-[width] duration-200 ease-out',
            activityDock === 'left' ? 'left-0 border-r' : 'right-0 border-l',
          ].join(' ')}
          data-dock={activityDock}
          data-expanded="false"
        >
          <button
            onClick={() => setExpanded(true)}
            className="flex flex-col items-center gap-1.5 hover:opacity-80 transition-opacity focus-visible:outline-2 focus-visible:outline-accent rounded-sm p-1"
            aria-label="Expand activity monitor"
          >
            <Activity size={18} className="text-accent" />
            {totalActive > 0 && (
              <span className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full bg-accent text-[10px] font-bold text-bg-base">
                {totalActive}
              </span>
            )}
          </button>
        </div>
      </>
    );
  }

  // ── Render: position-aware docked bar ────────────────────────────

  const dockPositionClasses = {
    bottom: 'bottom-0 left-0 right-0 border-t',
    top: 'top-0 left-0 right-0 border-b',
    left: `top-0 bottom-0 left-0 border-r flex flex-col ${expanded ? 'w-[320px]' : 'w-[320px]'}`,
    right: `top-0 bottom-0 right-0 border-l flex flex-col ${expanded ? 'w-[320px]' : 'w-[320px]'}`,
  };

  return (
    <>
      {/* Mobile pill */}
      <MobilePill totalActive={totalActive} navigate={navigate} />

      {/* Desktop dock */}
      <div
        className={[
          'hidden md:block fixed z-40 bg-bg-surface/90 backdrop-blur-xl',
          'border-white/[0.08] shadow-[0_8px_32px_-8px_rgba(0,0,0,0.55)]',
          'transition-[width,height] duration-200 ease-out',
          dockPositionClasses[activityDock],
        ].join(' ')}
        data-dock={activityDock}
        data-expanded={expanded}
      >
        {/* ── 1. Header strip (always visible) ───────────────────── */}
        <HeaderStrip
          workerHealth={workerHealth}
          wsConnected={wsConnected}
          queueStatus={
            queueStatus
              ? {
                  active: queueStatus.active,
                  queued: queueStatus.queued,
                  max_concurrent: queueStatus.max_concurrent,
                }
              : null
          }
          priority={priority}
          restartingWorker={restartingWorker}
          onRestartWorker={() => void handleRestartWorker()}
          onPriorityChange={handlePriorityChange}
          expanded={expanded}
          onToggleExpanded={() => setExpanded(!expanded)}
        />

        {/* ── 2. Expanded panel ───────────────────────────────────── */}
        {expanded && (
          <div className="border-t border-white/[0.05]">
            {/* Job cards */}
            <div
              className="overflow-y-auto px-3 py-2 flex flex-col gap-2"
              style={{ maxHeight: isVerticalDock ? 'calc(100vh - 200px)' : '220px' }}
              aria-busy={totalActive > 0}
            >
              {totalActive === 0 ? (
                <p className="text-xs text-txt-tertiary text-center py-4">
                  No active generations.
                </p>
              ) : (
                tasks.map((task) => (
                  <JobCard
                    key={`${task.type}-${task.id}`}
                    task={task}
                    cancelling={cancelling.has(task.id)}
                    onCancel={(t) => void handleCancel(t)}
                  />
                ))
              )}
            </div>

            {/* ── 3. Bulk actions ─────────────────────────────────── */}
            <BulkActions
              totalActive={totalActive}
              failedCount={failedCount}
              onPauseAll={handlePauseAll}
              onCancelAll={handleCancelAll}
              onRetryFailed={handleRetryFailed}
              onCleanup={handleCleanup}
            />
          </div>
        )}

        {/* Collapse chevron row — shown on horizontal docks when the
            expanded panel is closed, so users know they can click to open */}
        {!expanded && !isVerticalDock && (
          <div
            className={[
              'flex items-center justify-between px-3 h-0 overflow-hidden',
              'transition-all duration-200',
            ].join(' ')}
          />
        )}

        {/* Vertical dock collapse button (when expanded) */}
        {isVerticalDock && expanded && (
          <button
            onClick={() => setExpanded(false)}
            className="flex items-center justify-center w-full h-8 border-t border-white/[0.05] text-txt-tertiary hover:text-txt-secondary hover:bg-white/[0.03] transition-colors focus-visible:outline-2 focus-visible:outline-accent"
            aria-label="Collapse activity monitor"
          >
            <ChevronDown size={12} />
          </button>
        )}

        {/* Horizontal dock expand-indicator — the header strip button
            handles toggle, this chevron is purely decorative context */}
        {!isVerticalDock && (
          <div className="absolute top-0 right-12 h-8 flex items-center pointer-events-none">
            {expanded ? (
              <ChevronDown size={11} className="text-txt-tertiary" />
            ) : (
              <ChevronUp size={11} className="text-txt-tertiary" />
            )}
          </div>
        )}
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// MobilePill — floating bottom-right pill (< md breakpoint only)
// ---------------------------------------------------------------------------

function MobilePill({
  totalActive,
  navigate,
}: {
  totalActive: number;
  navigate: ReturnType<typeof useNavigate>;
}) {
  if (totalActive === 0) return null;
  return (
    <button
      onClick={() => navigate('/jobs')}
      className={[
        'fixed z-[98] md:hidden',
        'bottom-[76px] right-4',
        'flex items-center gap-2',
        'bg-bg-elevated/90 backdrop-blur-xl border border-white/[0.1] shadow-glass rounded-full px-3 py-1.5',
        'text-xs font-medium text-txt-primary',
        'transition-colors duration-fast hover:bg-white/[0.04]',
        'focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2',
      ].join(' ')}
      aria-label={`${totalActive} active job${totalActive > 1 ? 's' : ''} — tap to view`}
    >
      <Spinner size="sm" />
      <span>{totalActive} active</span>
    </button>
  );
}
