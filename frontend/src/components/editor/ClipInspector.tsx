import { type ReactNode } from 'react';
import { Gauge, ArrowRightFromLine, ArrowLeftFromLine } from 'lucide-react';
import { type Clip, clipSpeed, clipTimelineLength } from '@/lib/editor/timeline';

/** Clip inspector panel (Phase 2, PR 6a/6b). Shows the selected clip's source /
 *  timeline spans and lets you remap its playback speed and set fade in/out
 *  (opacity transitions). Home for the rest of PR 6's per-clip properties. */

const SPEED_PRESETS = [0.25, 0.5, 1, 1.5, 2, 4];
const FADE_PRESETS_SEC = [0, 0.25, 0.5, 1];

function FadeRow({
  label,
  icon,
  frames,
  fps,
  onSet,
}: {
  label: string;
  icon: ReactNode;
  frames: number;
  fps: number;
  onSet: (frames: number) => void;
}) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="flex items-center gap-1 text-txt-tertiary w-16 shrink-0">
        {icon}
        {label}
      </span>
      <div className="flex flex-wrap gap-1">
        {FADE_PRESETS_SEC.map((sec) => {
          const f = Math.round(sec * fps);
          const active = frames === f;
          return (
            <button
              key={sec}
              onClick={() => onSet(f)}
              className={`rounded px-1.5 py-0.5 tabular-nums ${
                active ? 'bg-accent text-white' : 'bg-bg-elevated text-txt-secondary hover:text-txt-primary'
              }`}
            >
              {sec === 0 ? 'Off' : `${sec}s`}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function ClipInspector({
  clip,
  fps,
  onSetSpeed,
  onSetFade,
}: {
  clip: Clip | null;
  fps: number;
  onSetSpeed: (clipId: string, speed: number) => void;
  onSetFade: (clipId: string, edge: 'in' | 'out', frames: number) => void;
}) {
  if (!clip) {
    return (
      <p className="text-xs text-txt-tertiary px-3 py-3">
        No clip selected — click a clip to inspect it.
      </p>
    );
  }

  const speed = clipSpeed(clip);
  const sourceLen = clip.outFrame - clip.inFrame;
  const timelineLen = clipTimelineLength(clip);

  return (
    <div className="px-3 py-2.5 space-y-3 text-xs">
      <div className="flex items-center gap-2">
        <span className="rounded bg-bg-elevated px-1.5 py-0.5 font-medium uppercase tracking-wide text-txt-secondary">
          {clip.kind}
        </span>
        <span className="text-txt-tertiary truncate" title={clip.sourceId ?? ''}>
          {clip.sourceId ?? '—'}
        </span>
      </div>

      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-txt-secondary tabular-nums">
        <dt className="text-txt-tertiary">Timeline</dt>
        <dd>
          {clip.startFrame}–{clip.endFrame} ({timelineLen}f · {(timelineLen / fps).toFixed(2)}s)
        </dd>
        <dt className="text-txt-tertiary">Source</dt>
        <dd>
          {clip.inFrame}–{clip.outFrame} ({sourceLen}f)
        </dd>
      </dl>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5 text-txt-tertiary">
          <Gauge size={12} />
          <span>Speed</span>
          <span className="ml-auto tabular-nums text-txt-secondary">{speed.toFixed(2)}×</span>
        </div>
        <div className="flex flex-wrap gap-1">
          {SPEED_PRESETS.map((p) => {
            const active = Math.abs(speed - p) < 0.01;
            return (
              <button
                key={p}
                onClick={() => onSetSpeed(clip.id, p)}
                className={`rounded px-2 py-0.5 tabular-nums ${
                  active
                    ? 'bg-accent text-white'
                    : 'bg-bg-elevated text-txt-secondary hover:text-txt-primary'
                }`}
              >
                {p}×
              </button>
            );
          })}
        </div>
      </div>

      <div className="space-y-1.5 border-t border-border/60 pt-2.5">
        <FadeRow
          label="Fade in"
          icon={<ArrowLeftFromLine size={12} />}
          frames={clip.fadeInFrames ?? 0}
          fps={fps}
          onSet={(f) => onSetFade(clip.id, 'in', f)}
        />
        <FadeRow
          label="Fade out"
          icon={<ArrowRightFromLine size={12} />}
          frames={clip.fadeOutFrames ?? 0}
          fps={fps}
          onSet={(f) => onSetFade(clip.id, 'out', f)}
        />
      </div>
    </div>
  );
}
