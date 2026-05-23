import { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import { useParams } from 'react-router-dom';
import {
  Play, Pause, Undo2, Redo2, ZoomIn, ZoomOut, Scissors, Trash2, MousePointer2, Magnet,
  Columns2, MoveHorizontal, ChevronsLeftRight, ArrowLeftToLine, ArrowRightToLine, Split, Save,
} from 'lucide-react';
import { useEditorStore } from '@/lib/editor/useEditorStore';
import { findClip } from '@/lib/editor/operations';
import { sampleTimeline } from '@/lib/editor/sample';
import { timelineDurationFrames, framesToSeconds, type ProjectTimeline } from '@/lib/editor/timeline';
import { editTimelineToProject, projectToEditTimeline } from '@/lib/editor/bridge';
import { createBackendRenderer } from '@/lib/editor/backendRenderer';
import { simulationRenderer } from '@/lib/editor/render';
import { editor as editorApi } from '@/lib/api';
import { createPlayback, type PlaybackController } from '@/lib/editor/engine/playback';
import { PreviewCanvas } from '@/components/editor/PreviewCanvas';
import { TimelineView, type EditorTool } from '@/components/editor/TimelineView';
import { MarkerList } from '@/components/editor/MarkerList';
import { MinimapView } from '@/components/editor/MinimapView';
import { ClipInspector } from '@/components/editor/ClipInspector';
import { CaptionsPanel } from '@/components/editor/CaptionsPanel';
import { ScenesPanel } from '@/components/editor/ScenesPanel';
import { RenderPanel } from '@/components/editor/RenderPanel';
import { HistoryPanel } from '@/components/editor/HistoryPanel';
import { SnapshotsPanel } from '@/components/editor/SnapshotsPanel';
import { useRenderQueue } from '@/lib/editor/useRenderQueue';
import {
  type EditorSnapshot,
  type RecoveryDraft,
  editorScope,
  loadSnapshots,
  addSnapshot,
  removeSnapshot,
  saveRecovery,
  loadRecovery,
  clearRecovery,
} from '@/lib/editor/persistence';

/**
 * EditorNext — the rebuilt NLE (`/editor-next`, ADR 002/003). Wires the store +
 * rAF playback engine to the preview canvas and the timeline. With an
 * `:episodeId` it loads/saves a real edit session through the existing backend
 * (bridged frames↔seconds, ADR 003) and autosaves debounced; bare, it loads the
 * sample timeline. The legacy editor at /episodes/:id/edit is untouched.
 */
function EditorNext() {
  const { episodeId } = useParams<{ episodeId?: string }>();
  const initial = useMemo(() => sampleTimeline(30), []);
  const store = useEditorStore(initial);
  const [loadStatus, setLoadStatus] = useState<'sample' | 'loading' | 'loaded' | 'error'>(
    episodeId ? 'loading' : 'sample',
  );
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [pxPerFrame, setPxPerFrame] = useState(1.2);
  const [playing, setPlaying] = useState(false);
  const [tool, setTool] = useState<EditorTool>('select');
  const [snapEnabled, setSnapEnabled] = useState(true);
  const [shuttleRate, setShuttleRate] = useState(0);
  const [inPoint, setInPoint] = useState<number | null>(null);
  const [outPoint, setOutPoint] = useState<number | null>(null);
  const [viewport, setViewport] = useState<{ from: number; to: number } | null>(null);

  // Keep the latest store reachable from once-created controllers/renderers.
  const storeRef = useRef(store);
  storeRef.current = store;
  const pbRef = useRef<PlaybackController | null>(null);

  // Real backend FFmpeg render when an episode is loaded; simulation for the sample.
  const renderer = useMemo(
    () =>
      episodeId
        ? createBackendRenderer({ episodeId, getTimeline: () => storeRef.current.timeline })
        : simulationRenderer,
    [episodeId],
  );
  const renderQueue = useRenderQueue(renderer);

  useEffect(() => {
    const pb = createPlayback({
      fps: initial.fps,
      durationFrames: () => timelineDurationFrames(storeRef.current.timeline),
      onFrame: (f) => {
        storeRef.current.setFrame(f);
        if (!pb.isPlaying()) {
          setPlaying(false);
          setShuttleRate(0);
        }
      },
    });
    pbRef.current = pb;
    return () => pb.dispose();
  }, [initial.fps]);

  // ── Real episode load / autosave (ADR 003) ─────────────────────────────────
  const loadedRef = useRef(false);
  const lastSyncedRef = useRef<ProjectTimeline | null>(null);

  useEffect(() => {
    if (!episodeId) return;
    let cancelled = false;
    setLoadStatus('loading');
    editorApi
      .get(episodeId)
      .then((session) => {
        if (cancelled) return;
        const tl = editTimelineToProject(session.timeline);
        storeRef.current.load(tl);
        lastSyncedRef.current = tl;
        loadedRef.current = true;
        setLoadStatus('loaded');
      })
      .catch(() => {
        if (!cancelled) setLoadStatus('error');
      });
    return () => {
      cancelled = true;
    };
  }, [episodeId]);

  const saveNow = useCallback(() => {
    if (!episodeId) return;
    const tl = storeRef.current.timeline;
    setSaveStatus('saving');
    editorApi
      .save(episodeId, projectToEditTimeline(tl))
      .then(() => {
        lastSyncedRef.current = tl;
        setSaveStatus('saved');
      })
      .catch(() => setSaveStatus('error'));
  }, [episodeId]);

  // Debounced autosave whenever the timeline changes after the initial load.
  useEffect(() => {
    if (!episodeId || !loadedRef.current) return;
    if (store.timeline === lastSyncedRef.current) return;
    setSaveStatus('saving');
    const id = window.setTimeout(saveNow, 800);
    return () => window.clearTimeout(id);
  }, [episodeId, store.timeline, saveNow]);

  // ── Snapshots + crash-recovery (PR 9b) ─────────────────────────────────────
  const scope = editorScope(episodeId);
  const [snapshots, setSnapshots] = useState<EditorSnapshot[]>(() => loadSnapshots(scope));
  const [recovery, setRecovery] = useState<RecoveryDraft | null>(null);
  const recoveryArmedRef = useRef(false);

  useEffect(() => {
    setSnapshots(loadSnapshots(scope));
  }, [scope]);

  // Once the session settles, offer recovery if a newer local draft differs.
  useEffect(() => {
    if (loadStatus !== 'loaded' && loadStatus !== 'sample') return;
    const draft = loadRecovery(scope);
    if (draft && JSON.stringify(draft.timeline) !== JSON.stringify(storeRef.current.timeline)) {
      setRecovery(draft);
    }
    recoveryArmedRef.current = true;
  }, [loadStatus, scope]);

  // Roll the crash-recovery draft forward as edits happen.
  useEffect(() => {
    if (!recoveryArmedRef.current) return;
    const id = window.setTimeout(() => saveRecovery(scope, storeRef.current.timeline), 1000);
    return () => window.clearTimeout(id);
  }, [scope, store.timeline]);

  const createSnapshot = useCallback(
    (name: string) => setSnapshots(addSnapshot(scope, name, storeRef.current.timeline)),
    [scope],
  );
  const restoreSnapshot = useCallback(
    (id: string) => {
      const snap = snapshots.find((s) => s.id === id);
      if (snap) storeRef.current.setTimeline(snap.timeline);
    },
    [snapshots],
  );
  const deleteSnapshot = useCallback((id: string) => setSnapshots(removeSnapshot(scope, id)), [scope]);

  const restoreRecovery = useCallback(() => {
    setRecovery((r) => {
      if (r) storeRef.current.setTimeline(r.timeline);
      return null;
    });
  }, []);
  const discardRecovery = useCallback(() => {
    clearRecovery(scope);
    setRecovery(null);
  }, [scope]);

  const seek = useCallback((f: number) => pbRef.current?.seekFrame(f), []);
  const onViewportChange = useCallback((from: number, to: number) => setViewport({ from, to }), []);

  const togglePlay = useCallback(() => {
    const pb = pbRef.current;
    if (!pb) return;
    pb.toggle();
    setPlaying(pb.isPlaying());
    setShuttleRate(pb.rate());
  }, []);

  const shuttle = useCallback((dir: 1 | -1) => {
    const pb = pbRef.current;
    if (!pb) return;
    pb.shuttle(dir);
    setPlaying(pb.isPlaying());
    setShuttleRate(pb.rate());
  }, []);

  const pausePlayback = useCallback(() => {
    pbRef.current?.pause();
    setPlaying(false);
    setShuttleRate(0);
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

  const trimStartToPlayhead = useCallback(() => {
    const s = storeRef.current;
    const found = s.selectedClipId ? findClip(s.timeline, s.selectedClipId) : null;
    if (found && s.frame > found.clip.startFrame && s.frame < found.clip.endFrame) {
      s.trimStart(found.clip.id, s.frame);
    }
  }, []);

  const trimEndToPlayhead = useCallback(() => {
    const s = storeRef.current;
    const found = s.selectedClipId ? findClip(s.timeline, s.selectedClipId) : null;
    if (found && s.frame > found.clip.startFrame && s.frame < found.clip.endFrame) {
      s.trimEnd(found.clip.id, s.frame);
    }
  }, []);

  const bladeAllAtPlayhead = useCallback(() => {
    storeRef.current.bladeAll(storeRef.current.frame);
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
      } else if (e.key === 'j' || e.key === 'J') {
        shuttle(-1);
      } else if (e.key === 'l' || e.key === 'L') {
        shuttle(1);
      } else if (e.key === 'k' || e.key === 'K') {
        pausePlayback();
      } else if (e.key === ',') {
        seek(Math.max(0, s.frame - 1));
      } else if (e.key === '.') {
        seek(s.frame + 1);
      } else if (e.key === 'i' || e.key === 'I') {
        setInPoint(s.frame);
      } else if (e.key === 'o' || e.key === 'O') {
        setOutPoint(s.frame);
      } else if (e.key === 'm' || e.key === 'M') {
        if (e.shiftKey) {
          const note = window.prompt('Marker note:');
          s.addMarker(s.frame, note || undefined);
        } else {
          s.addMarker(s.frame);
        }
      } else if (e.key === 's' || e.key === 'S') {
        if (e.shiftKey) bladeAllAtPlayhead();
        else splitAtPlayhead();
      } else if (e.key === '[') {
        trimStartToPlayhead();
      } else if (e.key === ']') {
        trimEndToPlayhead();
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
  }, [togglePlay, shuttle, pausePlayback, seek, splitAtPlayhead, deleteSelected, trimStartToPlayhead, trimEndToPlayhead, bladeAllAtPlayhead]);

  const duration = timelineDurationFrames(store.timeline);
  const selectedClip = store.selectedClipId
    ? findClip(store.timeline, store.selectedClipId)?.clip ?? null
    : null;
  const captions = useMemo(
    () =>
      store.timeline.tracks
        .filter((t) => t.kind === 'caption')
        .flatMap((t) => t.clips)
        .map((c) => ({ id: c.id, startFrame: c.startFrame, text: c.data?.caption?.text ?? '' }))
        .sort((a, b) => a.startFrame - b.startFrame),
    [store.timeline],
  );
  const scenes = store.timeline.scenes ?? [];

  return (
    <div className="p-4 space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-sm font-semibold text-txt-primary">Editor{episodeId ? '' : ' (preview)'}</span>
        <span className="text-[11px] text-txt-tertiary">
          {loadStatus === 'sample' && 'New NLE — sample timeline. Open from an episode to edit real media.'}
          {loadStatus === 'loading' && 'Loading episode…'}
          {loadStatus === 'error' && 'Could not load this episode.'}
          {loadStatus === 'loaded' && `Episode ${episodeId?.slice(0, 8)}`}
        </span>
        {episodeId && loadStatus === 'loaded' && (
          <div className="flex items-center gap-2 ml-auto">
            <span className="text-[11px] text-txt-tertiary">
              {saveStatus === 'saving' && 'Saving…'}
              {saveStatus === 'saved' && 'All changes saved'}
              {saveStatus === 'error' && 'Save failed — retry'}
            </span>
            <button
              onClick={saveNow}
              className="flex items-center gap-1 text-xs px-2 py-1 rounded-md bg-bg-elevated hover:bg-bg-hover text-txt-primary"
              title="Save now"
            >
              <Save size={13} /> Save
            </button>
          </div>
        )}
      </div>

      {recovery && (
        <div className="flex items-center gap-3 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs">
          <span className="text-amber-300">
            Recovered unsaved changes from {new Date(recovery.savedAt).toLocaleString()}.
          </span>
          <div className="ml-auto flex items-center gap-2">
            <button onClick={restoreRecovery} className="px-2 py-1 rounded bg-amber-500/20 text-amber-200 hover:bg-amber-500/30">
              Restore
            </button>
            <button onClick={discardRecovery} className="px-2 py-1 rounded text-txt-tertiary hover:text-txt-primary">
              Discard
            </button>
          </div>
        </div>
      )}

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
        <button onClick={() => setTool('roll')} className={`p-2 rounded-md ${tool === 'roll' ? 'bg-accent/20 text-accent' : 'bg-bg-elevated hover:bg-bg-hover text-txt-primary'}`} aria-label="Roll tool" title="Roll edit">
          <Columns2 size={16} />
        </button>
        <button onClick={() => setTool('slip')} className={`p-2 rounded-md ${tool === 'slip' ? 'bg-accent/20 text-accent' : 'bg-bg-elevated hover:bg-bg-hover text-txt-primary'}`} aria-label="Slip tool" title="Slip edit">
          <MoveHorizontal size={16} />
        </button>
        <button onClick={() => setTool('slide')} className={`p-2 rounded-md ${tool === 'slide' ? 'bg-accent/20 text-accent' : 'bg-bg-elevated hover:bg-bg-hover text-txt-primary'}`} aria-label="Slide tool" title="Slide edit">
          <ChevronsLeftRight size={16} />
        </button>
        <button onClick={() => setSnapEnabled((s) => !s)} className={`p-2 rounded-md ${snapEnabled ? 'bg-accent/20 text-accent' : 'bg-bg-elevated hover:bg-bg-hover text-txt-primary'}`} aria-label="Toggle snapping" title="Snapping">
          <Magnet size={16} />
        </button>
        <div className="w-px h-5 bg-border mx-1" />
        <button onClick={trimStartToPlayhead} disabled={!store.selectedClipId} className="p-2 rounded-md bg-bg-elevated hover:bg-bg-hover text-txt-primary disabled:opacity-40" aria-label="Trim start to playhead ([)" title="Trim start to playhead ([)">
          <ArrowLeftToLine size={16} />
        </button>
        <button onClick={trimEndToPlayhead} disabled={!store.selectedClipId} className="p-2 rounded-md bg-bg-elevated hover:bg-bg-hover text-txt-primary disabled:opacity-40" aria-label="Trim end to playhead (])" title="Trim end to playhead (])">
          <ArrowRightToLine size={16} />
        </button>
        <button onClick={bladeAllAtPlayhead} className="p-2 rounded-md bg-bg-elevated hover:bg-bg-hover text-txt-primary" aria-label="Blade all tracks (Shift+S)" title="Blade all tracks (Shift+S)">
          <Split size={16} />
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
        {Math.abs(shuttleRate) > 1 && (
          <span className="text-xs text-accent tabular-nums">{shuttleRate > 0 ? '▶' : '◀'} {Math.abs(shuttleRate)}×</span>
        )}
      </div>

      <MinimapView timeline={store.timeline} frame={store.frame} viewport={viewport} onSeek={seek} />

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
        onRoll={store.roll}
        onSlip={store.slip}
        onSlide={store.slide}
        inPoint={inPoint}
        outPoint={outPoint}
        onViewportChange={onViewportChange}
      />

      <div className="flex flex-wrap gap-3">
        <div className="border border-border rounded-lg bg-bg-surface w-72">
          <div className="px-2 py-1.5 border-b border-border text-[10px] font-display font-bold uppercase tracking-[0.15em] text-txt-tertiary">
            Clip
          </div>
          <ClipInspector
            clip={selectedClip}
            fps={store.timeline.fps}
            frame={store.frame}
            onSetSpeed={store.setClipSpeed}
            onSetFade={store.setClipFade}
            onSetTransform={store.setClipTransform}
            onSetTransformKeyframe={store.setTransformKeyframe}
            onRemoveTransformKeyframe={store.removeTransformKeyframe}
            onSetFilters={store.setClipFilters}
          />
        </div>

        <div className="border border-border rounded-lg bg-bg-surface flex-1 min-w-[16rem]">
          <div className="px-2 py-1.5 border-b border-border text-[10px] font-display font-bold uppercase tracking-[0.15em] text-txt-tertiary">
            Markers
          </div>
          <MarkerList
            markers={store.timeline.markers ?? []}
            fps={store.timeline.fps}
            onSeek={seek}
            onRemove={store.removeMarker}
            onEditNote={store.updateMarkerNote}
          />
        </div>

        <div className="border border-border rounded-lg bg-bg-surface flex-1 min-w-[16rem]">
          <div className="px-2 py-1.5 border-b border-border text-[10px] font-display font-bold uppercase tracking-[0.15em] text-txt-tertiary">
            Captions
          </div>
          <CaptionsPanel
            captions={captions}
            fps={store.timeline.fps}
            onSeek={seek}
            onEdit={store.setCaptionText}
            onRemove={store.removeClip}
            onAdd={() => store.addCaption(store.frame, Math.round(2 * store.timeline.fps))}
          />
        </div>

        <div className="border border-border rounded-lg bg-bg-surface flex-1 min-w-[16rem]">
          <div className="px-2 py-1.5 border-b border-border text-[10px] font-display font-bold uppercase tracking-[0.15em] text-txt-tertiary">
            Scenes
          </div>
          <ScenesPanel
            scenes={scenes}
            fps={store.timeline.fps}
            onSeek={seek}
            onRename={store.renameScene}
            onRemove={store.removeScene}
            onAdd={() => store.addScene(store.frame, `Scene ${scenes.length + 1}`)}
          />
        </div>

        <div className="border border-border rounded-lg bg-bg-surface w-72">
          <div className="px-2 py-1.5 border-b border-border text-[10px] font-display font-bold uppercase tracking-[0.15em] text-txt-tertiary">
            Render
          </div>
          <RenderPanel
            timeline={store.timeline}
            inPoint={inPoint}
            outPoint={outPoint}
            queue={renderQueue}
            mode={episodeId ? 'backend' : 'simulation'}
          />
        </div>

        <div className="border border-border rounded-lg bg-bg-surface w-60">
          <div className="px-2 py-1.5 border-b border-border text-[10px] font-display font-bold uppercase tracking-[0.15em] text-txt-tertiary">
            History
          </div>
          <HistoryPanel count={store.historyCount} index={store.historyIndex} onJump={store.jumpTo} />
        </div>

        <div className="border border-border rounded-lg bg-bg-surface w-60">
          <div className="px-2 py-1.5 border-b border-border text-[10px] font-display font-bold uppercase tracking-[0.15em] text-txt-tertiary">
            Snapshots
          </div>
          <SnapshotsPanel
            snapshots={snapshots}
            onCreate={createSnapshot}
            onRestore={restoreSnapshot}
            onRemove={deleteSnapshot}
          />
        </div>
      </div>
    </div>
  );
}

export default EditorNext;
