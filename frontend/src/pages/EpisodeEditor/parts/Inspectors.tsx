import { useCallback, useEffect, useRef, useState } from 'react';
import { Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { editor as editorApi, type EditTimelineClip, type CaptionWord } from '@/lib/api';

// ─── ClipInspector ───────────────────────────────────────────────────

export function ClipInspector({
  clip,
  onTrim,
  onDelete,
}: {
  clip: EditTimelineClip;
  onTrim: (in_s?: number, out_s?: number) => void;
  onDelete: () => void;
}) {
  return (
    <div className="space-y-3 text-xs">
      <div>
        <div className="text-txt-muted uppercase text-[10px] tracking-wider">Scene</div>
        <div>{clip.scene_number ? `#${clip.scene_number}` : clip.id}</div>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-0.5">
          <span className="text-txt-muted uppercase text-[10px] tracking-wider">In (s)</span>
          <input
            type="number"
            step={0.1}
            value={clip.in_s}
            onChange={(e) => onTrim(parseFloat(e.target.value) || 0, undefined)}
            className="px-2 py-1 bg-bg-base border border-white/[0.08] rounded text-sm"
          />
        </label>
        <label className="flex flex-col gap-0.5">
          <span className="text-txt-muted uppercase text-[10px] tracking-wider">Out (s)</span>
          <input
            type="number"
            step={0.1}
            value={clip.out_s}
            onChange={(e) => onTrim(undefined, parseFloat(e.target.value) || clip.in_s + 0.1)}
            className="px-2 py-1 bg-bg-base border border-white/[0.08] rounded text-sm"
          />
        </label>
      </div>
      <div className="text-txt-muted">
        Duration: <strong className="text-txt-primary">{(clip.out_s - clip.in_s).toFixed(2)}s</strong>
      </div>
      <Button variant="ghost" size="sm" className="text-error" onClick={onDelete}>
        <Trash2 className="w-3.5 h-3.5 mr-1" />
        Delete clip
      </Button>
    </div>
  );
}

// ─── OverlayInspector ────────────────────────────────────────────────

export function OverlayInspector({
  clip,
  onUpdate,
  onDelete,
}: {
  clip: EditTimelineClip;
  onUpdate: (patch: Partial<EditTimelineClip>) => void;
  onDelete: () => void;
}) {
  return (
    <div className="space-y-3 text-xs">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-txt-muted uppercase text-[10px] tracking-wider">Overlay</div>
          <div className="capitalize">{clip.kind}</div>
        </div>
        <Button variant="ghost" size="sm" className="text-error" onClick={onDelete}>
          <Trash2 className="w-3.5 h-3.5" />
        </Button>
      </div>

      {clip.kind === 'text' && (
        <>
          <label className="flex flex-col gap-0.5">
            <span className="text-txt-muted uppercase text-[10px] tracking-wider">Text</span>
            <input
              value={clip.text ?? ''}
              onChange={(e) => onUpdate({ text: e.target.value })}
              className="px-2 py-1 bg-bg-base border border-white/[0.08] rounded text-sm"
            />
          </label>
          <div className="grid grid-cols-2 gap-2">
            <label className="flex flex-col gap-0.5">
              <span className="text-txt-muted uppercase text-[10px] tracking-wider">Size</span>
              <input
                type="number"
                value={clip.font_size ?? 56}
                onChange={(e) => onUpdate({ font_size: parseInt(e.target.value, 10) || 56 })}
                className="px-2 py-1 bg-bg-base border border-white/[0.08] rounded text-sm"
              />
            </label>
            <label className="flex flex-col gap-0.5">
              <span className="text-txt-muted uppercase text-[10px] tracking-wider">Color</span>
              <input
                type="color"
                value={clip.color ?? '#ffffff'}
                onChange={(e) => onUpdate({ color: e.target.value })}
                className="px-1 py-0.5 bg-bg-base border border-white/[0.08] rounded text-sm h-8"
              />
            </label>
          </div>
          <label className="flex items-center gap-2 text-xs">
            <input
              type="checkbox"
              checked={!!clip.box}
              onChange={(e) => onUpdate({ box: e.target.checked })}
            />
            Background box
          </label>
        </>
      )}

      {clip.kind === 'shape' && (
        <div className="grid grid-cols-2 gap-2">
          <label className="flex flex-col gap-0.5">
            <span className="text-txt-muted uppercase text-[10px] tracking-wider">Color</span>
            <input
              type="color"
              value={clip.color ?? '#ffffff'}
              onChange={(e) => onUpdate({ color: e.target.value })}
              className="px-1 py-0.5 bg-bg-base border border-white/[0.08] rounded h-8"
            />
          </label>
          <label className="flex flex-col gap-0.5">
            <span className="text-txt-muted uppercase text-[10px] tracking-wider">W × H</span>
            <div className="flex gap-1">
              <input
                type="number"
                value={clip.w ?? 200}
                onChange={(e) => onUpdate({ w: parseInt(e.target.value, 10) || 200 })}
                className="flex-1 px-2 py-1 bg-bg-base border border-white/[0.08] rounded text-sm"
              />
              <input
                type="number"
                value={clip.h ?? 60}
                onChange={(e) => onUpdate({ h: parseInt(e.target.value, 10) || 60 })}
                className="flex-1 px-2 py-1 bg-bg-base border border-white/[0.08] rounded text-sm"
              />
            </div>
          </label>
        </div>
      )}

      {clip.kind === 'image' && (
        <label className="flex flex-col gap-0.5">
          <span className="text-txt-muted uppercase text-[10px] tracking-wider">Asset path</span>
          <input
            value={clip.asset_path ?? ''}
            onChange={(e) => onUpdate({ asset_path: e.target.value })}
            className="px-2 py-1 bg-bg-base border border-white/[0.08] rounded text-sm"
          />
        </label>
      )}

      <div className="grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-0.5">
          <span className="text-txt-muted uppercase text-[10px] tracking-wider">X</span>
          <input
            value={String(clip.x ?? '')}
            onChange={(e) => onUpdate({ x: e.target.value })}
            className="px-2 py-1 bg-bg-base border border-white/[0.08] rounded text-sm font-mono"
          />
        </label>
        <label className="flex flex-col gap-0.5">
          <span className="text-txt-muted uppercase text-[10px] tracking-wider">Y</span>
          <input
            value={String(clip.y ?? '')}
            onChange={(e) => onUpdate({ y: e.target.value })}
            className="px-2 py-1 bg-bg-base border border-white/[0.08] rounded text-sm font-mono"
          />
        </label>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-0.5">
          <span className="text-txt-muted uppercase text-[10px] tracking-wider">Start (s)</span>
          <input
            type="number"
            step={0.1}
            value={clip.start_s}
            onChange={(e) =>
              onUpdate({ start_s: parseFloat(e.target.value) || 0 })
            }
            className="px-2 py-1 bg-bg-base border border-white/[0.08] rounded text-sm"
          />
        </label>
        <label className="flex flex-col gap-0.5">
          <span className="text-txt-muted uppercase text-[10px] tracking-wider">End (s)</span>
          <input
            type="number"
            step={0.1}
            value={clip.end_s}
            onChange={(e) =>
              onUpdate({ end_s: parseFloat(e.target.value) || clip.start_s + 0.1 })
            }
            className="px-2 py-1 bg-bg-base border border-white/[0.08] rounded text-sm"
          />
        </label>
      </div>

      <div className="text-[10px] text-txt-muted">
        X / Y accept FFmpeg expressions like <code>(w-text_w)/2</code>, <code>h-200</code>, etc.
      </div>
    </div>
  );
}

// ─── CaptionsInspector ───────────────────────────────────────────────

export function CaptionsInspector({
  episodeId,
  playhead,
}: {
  episodeId: string;
  playhead: number;
}) {
  const [words, setWords] = useState<CaptionWord[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const saveDeb = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    void editorApi
      .getCaptions(episodeId)
      .then((r) => {
        if (alive) setWords(r.words || []);
      })
      .catch(() => {
        if (alive) setWords([]);
      })
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [episodeId]);

  const save = useCallback(
    (next: CaptionWord[]) => {
      setWords(next);
      if (saveDeb.current) clearTimeout(saveDeb.current);
      saveDeb.current = setTimeout(async () => {
        setSaving(true);
        try {
          await editorApi.putCaptions(episodeId, next);
        } catch {
          /* autosave best-effort */
        } finally {
          setSaving(false);
        }
      }, 700);
    },
    [episodeId],
  );

  if (loading) {
    return <div className="text-xs text-txt-muted py-6 text-center">Loading caption words…</div>;
  }
  if (!words || words.length === 0) {
    return (
      <div className="text-xs text-txt-muted py-4">
        No word-level captions stored. Run the captions step on the episode first, then come back.
      </div>
    );
  }

  return (
    <div className="space-y-2 text-xs">
      <div className="flex items-center justify-between">
        <span className="text-txt-muted">{words.length} words</span>
        <span className="text-[10px] text-txt-muted">{saving ? 'Saving…' : 'Saved'}</span>
      </div>
      <div className="max-h-[420px] overflow-y-auto space-y-1 pr-1">
        {words.map((w, i) => {
          const active = playhead >= w.start_seconds && playhead < w.end_seconds;
          return (
            <div
              key={i}
              className={[
                'flex items-center gap-1 p-1.5 rounded border',
                active ? 'border-accent bg-accent/10' : 'border-white/[0.04]',
              ].join(' ')}
            >
              <input
                value={w.word}
                onChange={(e) => {
                  const next = [...words];
                  next[i] = { ...w, word: e.target.value };
                  save(next);
                }}
                className="flex-1 px-1.5 py-0.5 bg-bg-base border border-white/[0.08] rounded text-xs"
              />
              <input
                type="number"
                step={0.01}
                value={w.start_seconds}
                onChange={(e) => {
                  const next = [...words];
                  next[i] = { ...w, start_seconds: parseFloat(e.target.value) || 0 };
                  save(next);
                }}
                className="w-14 px-1 py-0.5 bg-bg-base border border-white/[0.08] rounded text-[10px] font-mono"
                title="Start (s)"
              />
              <input
                type="number"
                step={0.01}
                value={w.end_seconds}
                onChange={(e) => {
                  const next = [...words];
                  next[i] = { ...w, end_seconds: parseFloat(e.target.value) || w.start_seconds + 0.1 };
                  save(next);
                }}
                className="w-14 px-1 py-0.5 bg-bg-base border border-white/[0.08] rounded text-[10px] font-mono"
                title="End (s)"
              />
              <button
                onClick={() => {
                  const next = [...words];
                  next[i] = { ...w, emphasis: !w.emphasis };
                  save(next);
                }}
                className={[
                  'px-1.5 py-0.5 rounded text-[10px] font-semibold',
                  w.emphasis ? 'bg-accent text-bg-base' : 'bg-bg-elevated text-txt-muted',
                ].join(' ')}
                title="Emphasis"
              >
                !
              </button>
              <input
                type="color"
                value={w.color ?? '#ffffff'}
                onChange={(e) => {
                  const next = [...words];
                  next[i] = { ...w, color: e.target.value };
                  save(next);
                }}
                className="w-6 h-6 rounded cursor-pointer"
                title="Word color"
              />
              <button
                onClick={() => {
                  const next = words.filter((_, idx) => idx !== i);
                  save(next);
                }}
                className="text-error hover:bg-error/10 rounded px-1.5 py-0.5 text-[10px]"
                title="Delete word"
              >
                ✕
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
