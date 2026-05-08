// =============================================================================
// React Query — query-key registry
// =============================================================================
//
// Every hook in ``lib/queries/`` reads its key from this file. Keeping
// keys in one place lets us:
//
//   * invalidate sibling queries by family (``qc.invalidateQueries({
//     queryKey: keys.episodes.all })``)
//   * spot a typo'd key during code review (the registry is the source
//     of truth, not a string scattered across 12 hooks)
//
// Convention: each resource is an object with at minimum a ``.all``
// root key, plus narrower keys for parameterised queries.

export const keys = {
  episodes: {
    all: ['episodes'] as const,
    lists: () => [...keys.episodes.all, 'list'] as const,
    list: (params: { series_id?: string; status?: string; limit?: number }) =>
      [...keys.episodes.lists(), params] as const,
    recent: (limit: number) => [...keys.episodes.all, 'recent', limit] as const,
    detail: (id: string) => [...keys.episodes.all, 'detail', id] as const,
  },

  series: {
    all: ['series'] as const,
    lists: () => [...keys.series.all, 'list'] as const,
    list: () => [...keys.series.lists()] as const,
    detail: (id: string) => [...keys.series.all, 'detail', id] as const,
  },

  jobs: {
    all: ['jobs'] as const,
    active: () => [...keys.jobs.all, 'active'] as const,
    listAll: () => [...keys.jobs.all, 'all'] as const,
    status: () => [...keys.jobs.all, 'status'] as const,
  },

  license: {
    all: ['license'] as const,
    status: () => [...keys.license.all, 'status'] as const,
  },

  health: {
    all: ['health'] as const,
    overall: () => [...keys.health.all] as const,
  },

  storage: {
    all: ['storage'] as const,
    overall: () => [...keys.storage.all] as const,
  },

  audiobooks: {
    all: ['audiobooks'] as const,
    lists: () => [...keys.audiobooks.all, 'list'] as const,
    list: () => [...keys.audiobooks.lists()] as const,
    detail: (id: string) => [...keys.audiobooks.all, 'detail', id] as const,
  },

  voiceProfiles: {
    all: ['voice-profiles'] as const,
    list: (params?: { provider?: string; language_code?: string }) =>
      [...keys.voiceProfiles.all, 'list', params ?? {}] as const,
  },
} as const;
