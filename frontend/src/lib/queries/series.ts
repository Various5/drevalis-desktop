import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { series as api } from '@/lib/api';
import type { Series, SeriesCreate, SeriesUpdate } from '@/types';
import { keys } from './keys';

export function useSeries() {
  return useQuery({
    queryKey: keys.series.list(),
    queryFn: () => api.list(),
  });
}

export function useSeriesById(id: string | undefined) {
  return useQuery({
    queryKey: keys.series.detail(id ?? ''),
    queryFn: () => api.get(id ?? ''),
    enabled: Boolean(id),
  });
}

// ── Mutations ──────────────────────────────────────────────────────

export function useCreateSeries() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: SeriesCreate) => api.create(data),
    onSuccess: (created: Series) => {
      void qc.invalidateQueries({ queryKey: keys.series.all });
      qc.setQueryData(keys.series.detail(created.id), created);
    },
  });
}

export function useUpdateSeries() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: SeriesUpdate }) =>
      api.update(id, data),
    onSuccess: (updated: Series) => {
      void qc.invalidateQueries({ queryKey: keys.series.all });
      qc.setQueryData(keys.series.detail(updated.id), updated);
    },
  });
}

export function useDeleteSeries() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(id),
    onSuccess: (_data: unknown, id: string) => {
      void qc.invalidateQueries({ queryKey: keys.series.all });
      qc.removeQueries({ queryKey: keys.series.detail(id) });
      // Series cascade-deletes its episodes server-side. Drop the
      // episode list cache too so stale rows don't haunt EpisodesList.
      void qc.invalidateQueries({ queryKey: keys.episodes.all });
    },
  });
}
