// =============================================================================
// React Query hooks (Phase 3.2) — barrel
// =============================================================================
//
// Pages import from ``@/lib/queries`` rather than the per-resource
// modules. Keeps the import sites tidy and lets us reorganise the
// internals without touching consumers.

export * from './episodes';
export * from './series';
export * from './jobs';
export * from './misc';
export { keys as queryKeys } from './keys';
