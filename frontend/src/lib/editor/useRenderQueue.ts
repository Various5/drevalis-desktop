/**
 * useRenderQueue — Phase 2, PR 8. Drives the pure render-queue reducer in
 * `render.ts`, running one job at a time through an injected `Renderer`
 * (default: the labelled simulation). "Which job runs next" is derived from
 * state via `nextQueued`, so transitioning a job to `rendering` naturally
 * prevents a second start; cancellation aborts the in-flight encode.
 */

import { useCallback, useEffect, useMemo, useReducer, useRef } from 'react';
import {
  type RenderJob,
  type RenderSpec,
  type Renderer,
  queueReducer,
  nextQueued,
  simulationRenderer,
} from './render';

export interface RenderQueue {
  jobs: RenderJob[];
  enqueue: (spec: RenderSpec) => void;
  cancel: (id: string) => void;
  clearFinished: () => void;
}

export function useRenderQueue(renderer: Renderer = simulationRenderer): RenderQueue {
  const [state, dispatch] = useReducer(queueReducer, { jobs: [] });
  const abortRef = useRef<Map<string, AbortController>>(new Map());

  useEffect(() => {
    const job = nextQueued(state);
    if (!job) return;
    const controller = new AbortController();
    abortRef.current.set(job.id, controller);
    dispatch({ type: 'start', id: job.id });
    renderer
      .render(job.spec, (p) => dispatch({ type: 'progress', id: job.id, progress: p }), controller.signal)
      .then(() => dispatch({ type: 'done', id: job.id }))
      .catch((e: unknown) => {
        if (e instanceof Error && e.name === 'AbortError') dispatch({ type: 'cancel', id: job.id });
        else dispatch({ type: 'error', id: job.id, error: e instanceof Error ? e.message : String(e) });
      })
      .finally(() => abortRef.current.delete(job.id));
  }, [state, renderer]);

  const enqueue = useCallback((spec: RenderSpec) => {
    dispatch({ type: 'enqueue', job: { id: crypto.randomUUID(), spec, status: 'queued', progress: 0 } });
  }, []);

  const cancel = useCallback((id: string) => {
    abortRef.current.get(id)?.abort();
    dispatch({ type: 'cancel', id });
  }, []);

  const clearFinished = useCallback(() => dispatch({ type: 'clearFinished' }), []);

  return useMemo(
    () => ({ jobs: state.jobs, enqueue, cancel, clearFinished }),
    [state.jobs, enqueue, cancel, clearFinished],
  );
}
