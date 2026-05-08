import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { episodes as api } from '@/lib/api';
import type {
  Episode,
  EpisodeCreate,
  EpisodeListItem,
  EpisodeUpdate,
} from '@/types';
import { keys } from './keys';

// ---------------------------------------------------------------------------
// Episode queries (Phase 3.2)
// ---------------------------------------------------------------------------
//
// React Query owns the snapshot cache for episode lists + detail; the
// WebSocket (``useActiveJobsProgress``) owns the live in-flight job
// progress overlaid on top of these snapshots. Don't replace WS
// progress with query polling — see R6.

export interface EpisodesListParams {
  series_id?: string;
  status?: string;
  limit?: number;
}

export function useEpisodes(params: EpisodesListParams = {}) {
  return useQuery({
    queryKey: keys.episodes.list(params),
    queryFn: () => api.list(params),
  });
}

export function useRecentEpisodes(limit = 10) {
  return useQuery({
    queryKey: keys.episodes.recent(limit),
    queryFn: () => api.recent(limit),
  });
}

export function useEpisode(id: string | undefined) {
  return useQuery({
    queryKey: keys.episodes.detail(id ?? ''),
    queryFn: () => api.get(id ?? ''),
    enabled: Boolean(id),
  });
}

// ── Mutations ──────────────────────────────────────────────────────

export function useCreateEpisode() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: EpisodeCreate) => api.create(data),
    onSuccess: (created: Episode) => {
      void qc.invalidateQueries({ queryKey: keys.episodes.all });
      qc.setQueryData(keys.episodes.detail(created.id), created);
    },
  });
}

export function useUpdateEpisode() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: EpisodeUpdate }) =>
      api.update(id, data),
    onSuccess: (updated: Episode) => {
      void qc.invalidateQueries({ queryKey: keys.episodes.all });
      qc.setQueryData(keys.episodes.detail(updated.id), updated);
    },
  });
}

export function useDeleteEpisode() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(id),
    onSuccess: (_data: unknown, id: string) => {
      void qc.invalidateQueries({ queryKey: keys.episodes.all });
      qc.removeQueries({ queryKey: keys.episodes.detail(id) });
    },
  });
}

// Re-export the row type so callers don't need to thread @/types separately.
export type { EpisodeListItem };
