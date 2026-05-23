import { describe, it, expect } from 'vitest';
import {
  buildRenderSpec,
  queueReducer,
  nextQueued,
  RENDER_PRESETS,
  type QueueState,
  type RenderJob,
  type RenderSpec,
} from './render';
import { type ProjectTimeline } from './timeline';

const preset = RENDER_PRESETS[0]!;

const tl = (dur: number): ProjectTimeline => ({
  fps: 30,
  tracks: [
    {
      id: 'v',
      kind: 'video',
      name: 'v',
      locked: false,
      muted: false,
      solo: false,
      clips: [{ id: 'c', trackId: 'v', kind: 'video', sourceId: 's', inFrame: 0, outFrame: dur, startFrame: 0, endFrame: dur }],
    },
  ],
});

describe('buildRenderSpec', () => {
  it('renders the whole timeline for region "all"', () => {
    const s = buildRenderSpec(tl(300), preset, { kind: 'all' });
    expect([s.fromFrame, s.toFrame, s.frames]).toEqual([0, 300, 300]);
  });
  it('clamps a range to the timeline and normalises order', () => {
    const s = buildRenderSpec(tl(300), preset, { kind: 'range', from: 350, to: 100 });
    expect([s.fromFrame, s.toFrame, s.frames]).toEqual([100, 300, 200]);
  });
});

const spec: RenderSpec = { preset, fromFrame: 0, toFrame: 100, frames: 100 };
const job = (id: string, over: Partial<RenderJob> = {}): RenderJob => ({ id, spec, status: 'queued', progress: 0, ...over });

describe('queueReducer', () => {
  it('enqueues, starts, progresses, and completes', () => {
    let s: QueueState = { jobs: [] };
    s = queueReducer(s, { type: 'enqueue', job: job('a') });
    s = queueReducer(s, { type: 'start', id: 'a' });
    expect(s.jobs[0]!.status).toBe('rendering');
    s = queueReducer(s, { type: 'progress', id: 'a', progress: 0.5 });
    expect(s.jobs[0]!.progress).toBe(0.5);
    s = queueReducer(s, { type: 'done', id: 'a' });
    expect([s.jobs[0]!.status, s.jobs[0]!.progress]).toEqual(['done', 1]);
  });
  it('ignores progress for non-rendering jobs and cancels only live jobs', () => {
    let s: QueueState = { jobs: [job('a', { status: 'done', progress: 1 })] };
    s = queueReducer(s, { type: 'progress', id: 'a', progress: 0.2 });
    expect(s.jobs[0]!.progress).toBe(1);
    s = queueReducer(s, { type: 'cancel', id: 'a' });
    expect(s.jobs[0]!.status).toBe('done'); // terminal, not cancellable
  });
  it('clearFinished drops terminal jobs only', () => {
    const s: QueueState = {
      jobs: [job('a', { status: 'done' }), job('b', { status: 'queued' }), job('c', { status: 'cancelled' })],
    };
    expect(queueReducer(s, { type: 'clearFinished' }).jobs.map((j) => j.id)).toEqual(['b']);
  });
});

describe('nextQueued', () => {
  it('returns the first queued job when nothing is rendering', () => {
    expect(nextQueued({ jobs: [job('a', { status: 'done' }), job('b'), job('c')] })!.id).toBe('b');
  });
  it('returns undefined while a job is rendering', () => {
    expect(nextQueued({ jobs: [job('a', { status: 'rendering' }), job('b')] })).toBeUndefined();
  });
});
