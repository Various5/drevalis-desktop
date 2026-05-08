import { useCallback } from 'react';
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query';
import { auth } from '@/lib/api';

// ---------------------------------------------------------------------------
// Per-user UI preferences hook
// ---------------------------------------------------------------------------
//
// One TanStack Query entry backs the whole prefs blob. Top-level keys
// are namespaced by feature (``dashboard_layout``, ``theme``,
// ``calendar_view``, …) — see ``api/routes/auth.py:update_preferences``
// for the merge semantics.
//
// Usage:
//
//   const { prefs, update, isLoading } = usePreferences<DashboardLayout>('dashboard_layout');
//   update({ widgets: ['stats', 'recent'] });   // merges in
//   update(null);                               // clears the namespace
//
// The hook is intentionally typed as ``T | undefined`` — callers
// fall back to defaults when prefs haven't been written yet.

const QUERY_KEY = ['auth', 'preferences'] as const;

interface PreferencesQueryShape {
  data: Record<string, unknown> | undefined;
  isLoading: boolean;
}

export function useAllPreferences(): PreferencesQueryShape {
  const q = useQuery({
    queryKey: QUERY_KEY,
    queryFn: () => auth.getPreferences(),
    // Layout / theme prefs are stable; refetch on focus would be
    // disruptive (e.g. drag-drop layout briefly resets while a stale
    // query lands). Keep them fresh-on-mount and never auto-refetch.
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
  return { data: q.data, isLoading: q.isPending };
}

/** Read + write a single namespaced preference key. */
export function usePreferences<T = unknown>(
  namespace: string,
): {
  prefs: T | undefined;
  update: (next: T | null) => Promise<void>;
  isLoading: boolean;
} {
  const queryClient = useQueryClient();
  const { data, isLoading } = useAllPreferences();

  const mutation = useMutation({
    mutationFn: (patch: Record<string, unknown>) => auth.updatePreferences(patch),
    onSuccess: (full) => {
      queryClient.setQueryData(QUERY_KEY, full);
    },
  });

  const update = useCallback(
    async (next: T | null) => {
      await mutation.mutateAsync({ [namespace]: next as unknown });
    },
    [mutation, namespace],
  );

  const prefs = data ? (data[namespace] as T | undefined) : undefined;
  return { prefs, update, isLoading };
}
