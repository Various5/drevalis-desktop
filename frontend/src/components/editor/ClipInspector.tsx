import { type ReactNode, useEffect, useState } from 'react';
import { Gauge, ArrowRightFromLine, ArrowLeftFromLine, Move, Sliders, RotateCcw, Diamond } from 'lucide-react';
import {
  type Clip,
  type ClipTransform,
  type ClipFilters,
  type TransformProp,
  clipSpeed,
  clipTimelineLength,
  effectiveTransform,
} from '@/lib/editor/timeline';

/** Clip inspector panel (Phase 2, PR 6/9c). Shows the selected clip's source /
 *  timeline spans and edits its per-clip properties: speed remap, fade in/out,
 *  geometry transform (scale / position / rotation / opacity, keyframable) and
 *  colour filters. Slider edits commit on release so a drag is a single undo
 *  step; the ◆ toggles a transform keyframe at the playhead. */

const SPEED_PRESETS = [0.25, 0.5, 1, 1.5, 2, 4];
const FADE_PRESETS_SEC = [0, 0.25, 0.5, 1];

const NEUTRAL_TRANSFORM: Required<ClipTransform> = { scale: 1, x: 0, y: 0, rotation: 0, opacity: 1 };
const NEUTRAL_FILTERS: Required<ClipFilters> = { brightness: 1, contrast: 1, saturation: 1 };

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

/** A range slider that tracks its value locally and commits on release, so a
 *  drag produces one undo entry rather than dozens. */
function RangeControl({
  label,
  value,
  min,
  max,
  step,
  fmt,
  onCommit,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  fmt: (v: number) => string;
  onCommit: (v: number) => void;
}) {
  const [local, setLocal] = useState(value);
  // Resync if the value changes externally (selection change, undo/redo).
  useEffect(() => setLocal(value), [value]);
  return (
    <label className="flex items-center gap-2">
      <span className="text-txt-tertiary w-14 shrink-0">{label}</span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={local}
        onChange={(e) => setLocal(parseFloat(e.target.value))}
        onPointerUp={() => onCommit(local)}
        onKeyUp={() => onCommit(local)}
        className="flex-1 accent-accent"
      />
      <span className="tabular-nums text-txt-secondary w-11 text-right">{fmt(local)}</span>
    </label>
  );
}

const pct = (v: number) => `${Math.round(v * 100)}%`;

export function ClipInspector({
  clip,
  fps,
  frame,
  onSetSpeed,
  onSetFade,
  onSetTransform,
  onSetTransformKeyframe,
  onRemoveTransformKeyframe,
  onSetFilters,
}: {
  clip: Clip | null;
  fps: number;
  frame: number;
  onSetSpeed: (clipId: string, speed: number) => void;
  onSetFade: (clipId: string, edge: 'in' | 'out', frames: number) => void;
  onSetTransform: (clipId: string, patch: Partial<ClipTransform>) => void;
  onSetTransformKeyframe: (clipId: string, prop: TransformProp, frame: number, value: number) => void;
  onRemoveTransformKeyframe: (clipId: string, prop: TransformProp, frame: number) => void;
  onSetFilters: (clipId: string, patch: Partial<ClipFilters>) => void;
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
  const visual = clip.kind === 'video' || clip.kind === 'overlay';
  const f = { ...NEUTRAL_FILTERS, ...clip.data?.filters };

  // Effective (keyframe-sampled) transform at the playhead, and per-prop state.
  const local = frame - clip.startFrame;
  const eff = { ...NEUTRAL_TRANSFORM, ...effectiveTransform(clip, frame) };
  const kfs = clip.data?.transformKeyframes;

  const transformRow = (
    prop: TransformProp,
    label: string,
    min: number,
    max: number,
    step: number,
    fmt: (v: number) => string,
  ) => {
    const list = kfs?.[prop];
    const hasKf = (list?.length ?? 0) > 0;
    const here = list?.some((k) => k.frame === local) ?? false;
    const value = eff[prop];
    return (
      <div key={prop} className="flex items-center gap-1.5">
        <button
          onClick={() =>
            here
              ? onRemoveTransformKeyframe(clip.id, prop, local)
              : onSetTransformKeyframe(clip.id, prop, local, value)
          }
          title={here ? 'Remove keyframe at playhead' : 'Add keyframe at playhead'}
          aria-label="Toggle transform keyframe"
          className={`shrink-0 ${here ? 'text-amber-400' : hasKf ? 'text-amber-400/50 hover:text-amber-400' : 'text-txt-tertiary hover:text-txt-primary'}`}
        >
          <Diamond size={11} fill={here ? 'currentColor' : 'none'} />
        </button>
        <div className="flex-1">
          <RangeControl
            label={label}
            value={value}
            min={min}
            max={max}
            step={step}
            fmt={fmt}
            onCommit={(v) =>
              hasKf ? onSetTransformKeyframe(clip.id, prop, local, v) : onSetTransform(clip.id, { [prop]: v })
            }
          />
        </div>
      </div>
    );
  };

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
          onSet={(frames) => onSetFade(clip.id, 'in', frames)}
        />
        <FadeRow
          label="Fade out"
          icon={<ArrowRightFromLine size={12} />}
          frames={clip.fadeOutFrames ?? 0}
          fps={fps}
          onSet={(frames) => onSetFade(clip.id, 'out', frames)}
        />
      </div>

      {visual && (
        <>
          <div className="space-y-1.5 border-t border-border/60 pt-2.5">
            <div className="flex items-center gap-1.5 text-txt-tertiary">
              <Move size={12} />
              <span>Transform</span>
              <span className="text-[10px] text-txt-tertiary/70">◆ keyframe</span>
              <button
                onClick={() => onSetTransform(clip.id, NEUTRAL_TRANSFORM)}
                className="ml-auto hover:text-txt-primary"
                title="Reset transform"
                aria-label="Reset transform"
              >
                <RotateCcw size={11} />
              </button>
            </div>
            {transformRow('scale', 'Scale', 0.1, 4, 0.05, (v) => `${v.toFixed(2)}×`)}
            {transformRow('x', 'X', -1, 1, 0.01, pct)}
            {transformRow('y', 'Y', -1, 1, 0.01, pct)}
            {transformRow('rotation', 'Rotate', -180, 180, 1, (v) => `${Math.round(v)}°`)}
            {transformRow('opacity', 'Opacity', 0, 1, 0.01, pct)}
          </div>

          <div className="space-y-1.5 border-t border-border/60 pt-2.5">
            <div className="flex items-center gap-1.5 text-txt-tertiary">
              <Sliders size={12} />
              <span>Filters</span>
              <button
                onClick={() => onSetFilters(clip.id, NEUTRAL_FILTERS)}
                className="ml-auto hover:text-txt-primary"
                title="Reset filters"
                aria-label="Reset filters"
              >
                <RotateCcw size={11} />
              </button>
            </div>
            <RangeControl label="Bright" value={f.brightness} min={0} max={2} step={0.05} fmt={pct} onCommit={(v) => onSetFilters(clip.id, { brightness: v })} />
            <RangeControl label="Contrast" value={f.contrast} min={0} max={2} step={0.05} fmt={pct} onCommit={(v) => onSetFilters(clip.id, { contrast: v })} />
            <RangeControl label="Sat" value={f.saturation} min={0} max={2} step={0.05} fmt={pct} onCommit={(v) => onSetFilters(clip.id, { saturation: v })} />
          </div>
        </>
      )}
    </div>
  );
}
