import { useState } from 'react';
import { Film, Plus, X, Trash2 } from 'lucide-react';
import { type ProjectTimeline } from '@/lib/editor/timeline';
import {
  type RenderRegion,
  type RenderStatus,
  RENDER_PRESETS,
  buildRenderSpec,
} from '@/lib/editor/render';
import { type RenderQueue } from '@/lib/editor/useRenderQueue';

/** Render panel (Phase 2, PR 8). Pick an output preset and region (whole
 *  timeline or the in/out range), preview the resolved spec, and queue renders.
 *  Encoding runs through the injected Renderer — the dev route uses a labelled
 *  simulation until the FFmpeg backend is wired (ADR 002, real-media PR). */

function fmtDuration(frames: number, fps: number): string {
  const totalSec = frames / fps;
  const m = Math.floor(totalSec / 60);
  const s = Math.round(totalSec % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

const STATUS_STYLE: Record<RenderStatus, string> = {
  queued: 'text-txt-tertiary',
  rendering: 'text-accent',
  done: 'text-emerald-400',
  error: 'text-error',
  cancelled: 'text-txt-tertiary',
};

export function RenderPanel({
  timeline,
  inPoint,
  outPoint,
  queue,
  mode = 'simulation',
}: {
  timeline: ProjectTimeline;
  inPoint: number | null;
  outPoint: number | null;
  queue: RenderQueue;
  mode?: 'simulation' | 'backend';
}) {
  const [presetId, setPresetId] = useState(RENDER_PRESETS[0]!.id);
  const [useRegion, setUseRegion] = useState(false);

  const preset = RENDER_PRESETS.find((p) => p.id === presetId) ?? RENDER_PRESETS[0]!;
  const hasRange = inPoint != null && outPoint != null && outPoint > inPoint;
  const region: RenderRegion =
    useRegion && hasRange ? { kind: 'range', from: inPoint, to: outPoint } : { kind: 'all' };
  const spec = buildRenderSpec(timeline, preset, region);

  return (
    <div className="px-3 py-2.5 space-y-2.5 text-xs">
      <label className="flex items-center gap-2">
        <span className="text-txt-tertiary w-14 shrink-0">Preset</span>
        <select
          value={presetId}
          onChange={(e) => setPresetId(e.target.value)}
          className="flex-1 bg-bg-elevated rounded px-1.5 py-1 text-txt-primary outline-none"
        >
          {RENDER_PRESETS.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label}
            </option>
          ))}
        </select>
      </label>

      <label className={`flex items-center gap-2 ${hasRange ? '' : 'opacity-50'}`}>
        <input
          type="checkbox"
          checked={useRegion && hasRange}
          disabled={!hasRange}
          onChange={(e) => setUseRegion(e.target.checked)}
          className="accent-accent"
        />
        <span className="text-txt-secondary">
          In/out region only {hasRange ? '' : '(set I and O first)'}
        </span>
      </label>

      <div className="text-txt-tertiary tabular-nums">
        {preset.width}×{preset.height} · {preset.fps}fps · {preset.format} ·{' '}
        {fmtDuration(spec.frames, timeline.fps)} ({spec.frames}f
        {spec.fromFrame > 0 ? `, from ${spec.fromFrame}` : ''})
      </div>

      <button
        onClick={() => queue.enqueue(spec)}
        disabled={spec.frames <= 0}
        className="flex items-center gap-1.5 rounded bg-accent text-white px-2.5 py-1 hover:opacity-90 disabled:opacity-40"
      >
        <Film size={13} />
        <Plus size={12} />
        Queue render
      </button>

      {queue.jobs.length > 0 && (
        <ul className="divide-y divide-border/60 border-t border-border/60 pt-1">
          {queue.jobs.map((job) => (
            <li key={job.id} className="py-1.5 space-y-1">
              <div className="flex items-center gap-2">
                <span className="tabular-nums text-txt-secondary truncate">
                  {job.spec.preset.label} · {fmtDuration(job.spec.frames, timeline.fps)}
                </span>
                <span className={`ml-auto capitalize ${STATUS_STYLE[job.status]}`}>{job.status}</span>
                {(job.status === 'queued' || job.status === 'rendering') && (
                  <button onClick={() => queue.cancel(job.id)} className="text-txt-tertiary hover:text-error" aria-label="Cancel render">
                    <X size={13} />
                  </button>
                )}
              </div>
              {job.status === 'rendering' && (
                <div className="h-1 rounded bg-bg-elevated overflow-hidden">
                  <div className="h-full bg-accent transition-[width]" style={{ width: `${Math.round(job.progress * 100)}%` }} />
                </div>
              )}
              {job.status === 'error' && job.error && <p className="text-error">{job.error}</p>}
            </li>
          ))}
          <li className="pt-1">
            <button
              onClick={queue.clearFinished}
              className="flex items-center gap-1.5 text-txt-tertiary hover:text-txt-primary"
            >
              <Trash2 size={12} />
              Clear finished
            </button>
          </li>
        </ul>
      )}

      <p className="text-[10px] text-txt-tertiary leading-snug border-t border-border/60 pt-2">
        {mode === 'backend'
          ? 'Renders the full saved timeline through the backend (FFmpeg) — fades, colour filters, transform (scale/position/rotation + their keyframes), opacity and speed all bake in. Preset/region aren’t sent yet. The finished MP4 lands in the episode output.'
          : 'Sample timeline: rendering is simulated. Open from an episode to run a real FFmpeg export.'}
      </p>
    </div>
  );
}
