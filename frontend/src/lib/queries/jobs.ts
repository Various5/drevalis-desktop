import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { jobs as api } from '@/lib/api';
import { keys } from './keys';

// ---------------------------------------------------------------------------
// Job queries (Phase 3.2)
// ---------------------------------------------------------------------------
//
// ``useActiveJobs`` is the React Query mirror of the active-jobs list,
// used by the Sidebar / MobileNav / Dashboard / ActivityMonitor for
// counts. It refetches every 5s ONLY while the WebSocket reports
// active jobs, and pauses on hidden tabs (R6: Query for snapshots,
// WS for progress; the WS handler also calls ``invalidateQueries`` so
// counts update instantly without waiting for the interval).
//
// ``useAllJobs`` is the history table used by the Jobs page —
// regular staleTime, no interval (pageviews trigger a refetch).

export function useActiveJobs(opts?: { hasActive?: boolean }) {
  const hasActive = opts?.hasActive ?? true;
  return useQuery({
    queryKey: keys.jobs.active(),
    queryFn: () => api.active(),
    // Pause polling when no jobs are active and when the tab is hidden.
    refetchInterval: hasActive ? 5000 : false,
    refetchIntervalInBackground: false,
  });
}

export function useJobsStatus(opts?: { hasActive?: boolean }) {
  const hasActive = opts?.hasActive ?? true;
  return useQuery({
    queryKey: keys.jobs.status(),
    queryFn: () => api.status(),
    refetchInterval: hasActive ? 5000 : false,
    refetchIntervalInBackground: false,
  });
}

/**
 * Unified tasks-active list (episodes + audiobooks + script jobs)
 * used by the ActivityMonitor. Polls every 5s while the WebSocket
 * reports active jobs, otherwise stops polling. Replaces the
 * previous unconditional 3s setInterval (a) on the docked rail.
 */
export function useActiveTasks(opts?: { hasActive?: boolean }) {
  const hasActive = opts?.hasActive ?? true;
  return useQuery({
    queryKey: [...keys.jobs.all, 'tasks-active'] as const,
    queryFn: () => api.tasksActive(),
    refetchInterval: hasActive ? 5000 : false,
    refetchIntervalInBackground: false,
  });
}

/**
 * Worker heartbeat. Refreshes every 30s; pauses on hidden tabs.
 * Mounted on the ActivityMonitor (worker-health pill).
 */
export function useWorkerHealth() {
  return useQuery({
    queryKey: [...keys.jobs.all, 'worker-health'] as const,
    queryFn: () => api.workerHealth(),
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
  });
}

/**
 * Full jobs history — used by the /jobs page table.
 *
 * The refetch interval is derived FROM the cached result: we poll at
 * 5s while any row is ``running`` or ``queued``, and stop once
 * everything is settled. The previous code polled every 5s
 * unconditionally and never paused on hidden tabs.
 */
export function useAllJobs() {
  return useQuery({
    queryKey: keys.jobs.listAll(),
    queryFn: () => api.all({ limit: 200 }),
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return false;
      const hasActive = data.some(
        (j) => j.status === 'running' || j.status === 'queued',
      );
      return hasActive ? 5000 : false;
    },
    refetchIntervalInBackground: false,
  });
}

// ── Mutations ──────────────────────────────────────────────────────

export function useCancelAllJobs() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.cancelAll(),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.jobs.all });
      // Cancellation flips episode status — list view needs a refresh.
      void qc.invalidateQueries({ queryKey: keys.episodes.all });
    },
  });
}

export function useRetryAllFailed() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (priority?: 'shorts_first' | 'longform_first' | 'fifo') =>
      api.retryAllFailed(priority),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.jobs.all });
      void qc.invalidateQueries({ queryKey: keys.episodes.all });
    },
  });
}
