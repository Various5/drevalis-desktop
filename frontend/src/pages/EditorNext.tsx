import { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import { Play, Pause, Undo2, Redo2, ZoomIn, ZoomOut, Scissors, Trash2, MousePointer2, Magnet } from 'lucide-react';
import { useEditorStore } from '@/lib/editor/useEditorStore';
import { sampleTimeline } from '@/lib/editor/sample';
import { timelineDurationFrames, framesToSeconds } from '@/lib/editor/timeline';
import { createPlayback, type PlaybackController } from '@/lib/editor/engine/playback';
import { PreviewCanvas } from '@/components/editor/PreviewCanvas';
import { TimelineView, type EditorTool } from '@/components/editor/TimelineView';

/**
 * EditorNext — the rebuilt NLE behind a flagged dev route (`/editor-next`),
 * Phase 2, PR 3. Wires the store + rAF playback engine to the preview canvas
 * and the timeline. Loads a sample timeline; real episode load/save lands in a
 * later PR. The legacy editor at /episodes/:id/edit is untouched.
 */
function EditorNext() {
  const initial = useMemo(() => sampleTimeline(30), []);
  const store = useEditorStore(initial);
  const [pxPerFrame, setPxPerFrame] = useState(1.2);
  const [playing, setPlaying] = useState(false);
  const [tool, setTool] = useState<EditorTool>('select');
  const [snapEnabled, setSnapEnabled] = useState(true);

  // Keep the latest store reachable from the once-created playback controller.
  const storeRef = useRef(store);
  storeRef.current = store;
  const pbRef = useRef<PlaybackController | null>(null);

  useEffect(() => {
    const pb = createPlayback({
      fps: initial.fps,
      durationFrames: () => timelineDurationFrames(storeRef.current.timeline),
      onFrame: (f) => {
        storeRef.current.setFrame(f);
        if (!pb.isPlaying()) setPlaying(false); // resync at end
      },
    });
    pbRef.current = pb;
    return () => pb.dispose();
  }, [initial.fps]);

  const seek = useCallback((f: number) => pbRef.current?.seekFrame(f), []);

  const togglePlay = useCallback(() => {
    const pb = pbRef.current;
    if (!pb) return;
    pb.toggle();
    setPlaying(pb.isPlaying());
  }, []);

  const splitAtPlayhead = useCallback(() => {
    const s = storeRef.current;
    if (s.selectedClipId) s.splitClip(s.selectedClipId, s.frame, crypto.randomUUID());
  }, []);

  const deleteSelected = useCallback(() => {
    const s = storeRef.current;
    if (s.selectedClipId) {
      s.rippleDelete(s.selectedClipId);
      s.select(null);
    }
  }, []);

  // Keyboard transport + edits.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA') return;
      const s = storeRef.current;
      if (e.key === ' ') {
        e.preventDefault();
        togglePlay();
      } else if (e.key === 'ArrowLeft') {
        seek(Math.max(0, s.frame - (e.shiftKey ? 10 : 1)));
      } else if (e.key === 'ArrowRight') {
        seek(s.frame + (e.shiftKey ? 10 : 1));
      } else if (e.key === 's' || e.key === 'S') {
        splitAtPlayhead();
      } else if (e.key === 'v' || e.key === 'V') {
        setTool('select');
      } else if (e.key === 'b' || e.key === 'B') {
        setTool('razor');
      } else if (e.key === 'Delete' || e.key === 'Backspace') {
        deleteSelected();
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
        e.preventDefault();
        if (e.shiftKey) s.redo();
        else s.undo();
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y') {
        e.preventDefault();
        s.redo();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [togglePlay, seek, splitAtPlayhead, deleteSelected]);

  const duration = timelineDurationFrames(store.timeline);

  return (
    <div className="p-4 space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-sm font-semibold text-txt-primary">Editor (preview)</span>
        <span className="text-[11px] text-txt-tertiary">
          New NLE — flagged dev route. Sample timeline.
        </span>
      </div>

      <PreviewCanvas timeline={store.timeline} frame={store.frame} className="max-w-3xl mx-auto" />

      {/* Transport */}
      <div className="flex items-center gap-1.5 flex-wrap">
        <button onClick={togglePlay} className="p-2 rounded-md bg-bg-elevated hover:bg-bg-hover text-txt-primary" aria-label={playing ? 'Pause' : 'Play'}>
          {playing ? <Pause size={16} /> : <Play size={16} />}
        </button>
        <button onClick={() => store.undo()} disabled={!store.canUndo} className="p-2 rounded-md bg-bg-elevated hover:bg-bg-hover text-txt-primary disabled:opacity-40" aria-label="Undo">
          <Undo2 size={16} />
        </button>
        <button onClick={() => store.redo()} disabled={!store.canRedo} className="p-2 rounded-md bg-bg-elevated hover:bg-bg-hover text-txt-primary disabled:opacity-40" aria-label="Redo">
          <Redo2 size={16} />
        </button>
        <div className="w-px h-5 bg-border mx-1" />
        <button onClick={() => setTool('select')} className={`p-2 rounded-md ${tool === 'select' ? 'bg-accent/20 text-accent' : 'bg-bg-elevated hover:bg-bg-hover text-txt-primary'}`} aria-label="Select tool (V)" title="Select (V)">
          <MousePointer2 size={16} />
        </button>
        <button onClick={() => setTool('razor')} className={`p-2 rounded-md ${tool === 'razor' ? 'bg-accent/20 text-accent' : 'bg-bg-elevated hover:bg-bg-hover text-txt-primary'}`} aria-label="Razor tool (B)" title="Razor (B)">
          <Scissors size={16} />
        </button>
        <button onClick={() => setSnapEnabled((s) => !s)} className={`p-2 rounded-md ${snapEnabled ? 'bg-accent/20 text-accent' : 'bg-bg-elevated hover:bg-bg-hover text-txt-primary'}`} aria-label="Toggle snapping" title="Snapping">
          <Magnet size={16} />
        </button>
        <button onClick={deleteSelected} disabled={!store.selectedClipId} className="p-2 rounded-md bg-bg-elevated hover:bg-bg-hover text-txt-primary disabled:opacity-40" aria-label="Ripple delete selected (Del)">
          <Trash2 size={16} />
        </button>
        <div className="w-px h-5 bg-border mx-1" />
        <button onClick={() => setPxPerFrame((p) => Math.max(0.05, p / 1.3))} className="p-2 rounded-md bg-bg-elevated hover:bg-bg-hover text-txt-primary" aria-label="Zoom out">
          <ZoomOut size={16} />
        </button>
        <button onClick={() => setPxPerFrame((p) => Math.min(8, p * 1.3))} className="p-2 rounded-md bg-bg-elevated hover:bg-bg-hover text-txt-primary" aria-label="Zoom in">
          <ZoomIn size={16} />
        </button>
        <span className="text-xs text-txt-tertiary tabular-nums ml-1">
          {framesToSeconds(store.frame, store.timeline.fps).toFixed(2)}s / {framesToSeconds(duration, store.timeline.fps).toFixed(1)}s
        </span>
      </div>

      <TimelineView
        timeline={store.timeline}
        frame={store.frame}
        selectedClipId={store.selectedClipId}
        pxPerFrame={pxPerFrame}
        tool={tool}
        snapEnabled={snapEnabled}
        onSeek={seek}
        onSelectClip={store.select}
        onZoom={setPxPerFrame}
        onToggleTrackFlag={store.setTrackFlag}
        onMoveClip={store.moveClip}
        onTrimStart={store.trimStart}
        onTrimEnd={store.trimEnd}
        onSplitAt={(clipId, at) => store.splitClip(clipId, at, crypto.randomUUID())}
      />
    </div>
  );
}

export default EditorNext;
