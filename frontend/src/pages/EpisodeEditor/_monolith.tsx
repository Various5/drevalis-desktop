import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  ArrowLeft,
  Play,
  Pause,
  Rocket,
  Undo2,
  Redo2,
  MoveHorizontal,
} from 'lucide-react';
import { AssetPicker } from '@/components/assets/AssetPicker';
import { Button } from '@/components/ui/Button';
import { Spinner } from '@/components/ui/Spinner';
import { useToast } from '@/components/ui/Toast';
import { assets as assetsApi } from '@/lib/api';
import { findStampById } from '@/stamps/catalog';
import {
  editor as editorApi,
  formatError,
  type EditSession,
  type EditTimeline,
  type EditTimelineClip,
} from '@/lib/api';
import { ASSET_DRAG_MIME, STAMP_DRAG_MIME } from './parts/constants';
import { ToolsRail } from './parts/ToolsRail';
import { RightPanel } from './parts/RightPanel';
import { TimelineRuler, PreviewPlayer, TrackRow } from './parts/Timeline';

// ─── Helpers ────────────────────────────────────────────────────────

function waveformUrlFor(episodeId: string, trackId: string): string | null {
  if (trackId === 'voice') return `/api/v1/episodes/${episodeId}/editor/waveform?track=voice`;
  if (trackId === 'music') return `/api/v1/episodes/${episodeId}/editor/waveform?track=music`;
  return null;
}

// ─── Reducer for undo/redo ─────────────────────────────────────────

type Action =
  | { type: 'load'; timeline: EditTimeline }
  | { type: 'trim'; clipId: string; in_s?: number; out_s?: number }
  | { type: 'split'; clipId: string; at_s: number }
  | { type: 'delete'; clipId: string }
  | { type: 'reorder'; trackId: string; fromIndex: number; toIndex: number }
  | { type: 'add_overlay'; clip: EditTimelineClip }
  | { type: 'update_overlay'; clipId: string; patch: Partial<EditTimelineClip> }
  | {
      type: 'envelope';
      trackId: string;
      clipId: string;
      envelope: Array<[number, number]>;
    }
  | { type: 'undo' }
  | { type: 'redo' };

interface HistoryState {
  past: EditTimeline[];
  present: EditTimeline;
  future: EditTimeline[];
}

function reflow(timeline: EditTimeline): EditTimeline {
  // Re-chain video-track clips so start_s / end_s are sequential. Audio
  // / overlay tracks keep user-authored starts.
  const tracks = timeline.tracks.map((t) => {
    if (t.kind !== 'video') return t;
    let cursor = 0;
    const clips = t.clips.map((c) => {
      const dur = Math.max(0, c.out_s - c.in_s);
      const next: EditTimelineClip = {
        ...c,
        start_s: Math.round(cursor * 1000) / 1000,
        end_s: Math.round((cursor + dur) * 1000) / 1000,
      };
      cursor += dur;
      return next;
    });
    return { ...t, clips };
  });
  const videoTrack = tracks.find((t) => t.kind === 'video');
  const dur = videoTrack
    ? videoTrack.clips.reduce((acc, c) => acc + (c.out_s - c.in_s), 0)
    : timeline.duration_s;
  return { ...timeline, tracks, duration_s: Math.round(dur * 1000) / 1000 };
}

function applyAction(timeline: EditTimeline, action: Action): EditTimeline {
  switch (action.type) {
    case 'trim': {
      const tracks = timeline.tracks.map((t) => ({
        ...t,
        clips: t.clips.map((c) => {
          if (c.id !== action.clipId) return c;
          const next: EditTimelineClip = { ...c };
          if (action.in_s !== undefined) next.in_s = Math.max(0, action.in_s);
          if (action.out_s !== undefined) next.out_s = Math.max(next.in_s + 0.1, action.out_s);
          return next;
        }),
      }));
      return reflow({ ...timeline, tracks });
    }
    case 'split': {
      const tracks = timeline.tracks.map((t) => {
        if (t.kind !== 'video') return t;
        const idx = t.clips.findIndex((c) => c.id === action.clipId);
        if (idx === -1) return t;
        const clip = t.clips[idx]!;
        const splitLocal = action.at_s - clip.start_s + clip.in_s;
        if (splitLocal <= clip.in_s || splitLocal >= clip.out_s) return t;
        const left: EditTimelineClip = { ...clip, out_s: splitLocal };
        const right: EditTimelineClip = {
          ...clip,
          id: `${clip.id}-s${Date.now()}`,
          in_s: splitLocal,
        };
        const clips = [...t.clips.slice(0, idx), left, right, ...t.clips.slice(idx + 1)];
        return { ...t, clips };
      });
      return reflow({ ...timeline, tracks });
    }
    case 'delete': {
      const tracks = timeline.tracks.map((t) => ({
        ...t,
        clips: t.clips.filter((c) => c.id !== action.clipId),
      }));
      return reflow({ ...timeline, tracks });
    }
    case 'reorder': {
      const tracks = timeline.tracks.map((t) => {
        if (t.id !== action.trackId) return t;
        const clips = [...t.clips];
        const moved = clips.splice(action.fromIndex, 1)[0];
        if (!moved) return t;
        clips.splice(action.toIndex, 0, moved);
        return { ...t, clips };
      });
      return reflow({ ...timeline, tracks });
    }
    case 'add_overlay': {
      const tracks = timeline.tracks.map((t) =>
        t.id === 'overlay' ? { ...t, clips: [...t.clips, action.clip] } : t,
      );
      return { ...timeline, tracks };
    }
    case 'update_overlay': {
      const tracks = timeline.tracks.map((t) =>
        t.id === 'overlay'
          ? {
              ...t,
              clips: t.clips.map((c) =>
                c.id === action.clipId ? { ...c, ...action.patch } : c,
              ),
            }
          : t,
      );
      return { ...timeline, tracks };
    }
    case 'envelope': {
      const tracks = timeline.tracks.map((t) =>
        t.id === action.trackId
          ? {
              ...t,
              clips: t.clips.map((c) =>
                c.id === action.clipId ? { ...c, envelope: action.envelope } : c,
              ),
            }
          : t,
      );
      return { ...timeline, tracks };
    }
    default:
      return timeline;
  }
}

function historyReducer(state: HistoryState, action: Action): HistoryState {
  if (action.type === 'load') {
    return { past: [], present: action.timeline, future: [] };
  }
  if (action.type === 'undo') {
    if (!state.past.length) return state;
    const last = state.past[state.past.length - 1]!;
    return {
      past: state.past.slice(0, -1),
      present: last,
      future: [state.present, ...state.future],
    };
  }
  if (action.type === 'redo') {
    if (!state.future.length) return state;
    const nextState = state.future[0]!;
    return {
      past: [...state.past, state.present],
      present: nextState,
      future: state.future.slice(1),
    };
  }
  const nextTimeline = applyAction(state.present, action);
  if (nextTimeline === state.present) return state;
  return {
    // 200-step undo history. The previous cap (50) was enough for
    // small edits but lost context on real sessions.
    past: [...state.past.slice(-199), state.present],
    present: nextTimeline,
    future: [],
  };
}

// ─── Page ──────────────────────────────────────────────────────────

export default function EpisodeEditor() {
  const { episodeId } = useParams();
  const navigate = useNavigate();
  const { toast } = useToast();
  const [session, setSession] = useState<EditSession | null>(null);
  const [history, dispatch] = useReducer(historyReducer, {
    past: [],
    present: { duration_s: 0, tracks: [] },
    future: [],
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [rendering, setRendering] = useState(false);
  const [selectedClipId, setSelectedClipId] = useState<string | null>(null);
  const [assetPickerOpen, setAssetPickerOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [snapEnabled, setSnapEnabled] = useState(true);
  // Snap grid: 0.1s when zoomed in, 0.25s mid, 1s when zoomed out.
  const [zoom, setZoom] = useState(60); // px per second
  const snapStep = zoom >= 100 ? 0.1 : zoom >= 50 ? 0.25 : 1.0;
  const snap = useCallback(
    (t: number) => (snapEnabled ? Math.round(t / snapStep) * snapStep : t),
    [snapEnabled, snapStep],
  );
  const [playhead, setPlayhead] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [inspectorTab, setInspectorTab] = useState<'clip' | 'captions'>('clip');
  // Drives the right-panel external tab selection. When the
  // ToolsRail "Stamps" or "Image" buttons fire, we bump this so
  // the panel snaps to the matching tab.
  const [rightPanelTab, setRightPanelTab] = useState<
    'clip' | 'captions' | 'assets' | 'stamps' | undefined
  >(undefined);

  // Preview / timeline split (v0.21.1) — percentage of the center
  // column allocated to the preview. Persisted in localStorage so
  // returning users don't have to re-resize. Default 58% gives
  // enough timeline to see four tracks without scrolling on a 1080p
  // display while leaving the preview comfortably large.
  const [previewPct, setPreviewPct] = useState<number>(() => {
    if (typeof window === 'undefined') return 58;
    const stored = window.localStorage.getItem('drevalis.editor.previewPct');
    const parsed = stored ? parseFloat(stored) : NaN;
    return Number.isFinite(parsed) && parsed >= 25 && parsed <= 80
      ? parsed
      : 58;
  });
  useEffect(() => {
    try {
      window.localStorage.setItem(
        'drevalis.editor.previewPct',
        String(previewPct),
      );
    } catch {
      /* ignore */
    }
  }, [previewPct]);
  // Drag-state for the splitter between preview and timeline.
  const splitContainerRef = useRef<HTMLDivElement | null>(null);
  const draggingSplit = useRef(false);

  // Aspect ratio of the playable source (read from the <video>
  // element's natural dimensions when available). Defaults to 9:16
  // for shorts which is the most common case.
  const [previewAspect, setPreviewAspect] = useState<string>('9 / 16');
  const [previewingProxy, setPreviewingProxy] = useState(false);
  const [proxyReadyTs, setProxyReadyTs] = useState<number | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [savedAgo, setSavedAgo] = useState<string>('');
  const saveDebounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Load session.
  useEffect(() => {
    if (!episodeId) return;
    setLoading(true);
    void editorApi
      .get(episodeId)
      .then((s) => {
        setSession(s);
        dispatch({ type: 'load', timeline: s.timeline });
      })
      .catch((e) => toast.error('Failed to open editor', { description: formatError(e) }))
      .finally(() => setLoading(false));
  }, [episodeId, toast]);

  // Debounced autosave whenever the timeline changes.
  useEffect(() => {
    if (!episodeId || !session) return;
    if (saveDebounce.current) clearTimeout(saveDebounce.current);
    saveDebounce.current = setTimeout(async () => {
      setSaving(true);
      try {
        await editorApi.save(episodeId, history.present);
        setSavedAt(Date.now());
      } catch (err) {
        toast.error('Autosave failed', { description: formatError(err) });
      } finally {
        setSaving(false);
      }
    }, 900);
    return () => {
      if (saveDebounce.current) clearTimeout(saveDebounce.current);
    };
  }, [history.present, episodeId, session, toast]);

  // Relative "saved Xs ago" label, refreshed every 5s.
  useEffect(() => {
    if (!savedAt) return;
    const update = () => {
      const secs = Math.max(0, Math.round((Date.now() - savedAt) / 1000));
      if (secs < 5) setSavedAgo('just now');
      else if (secs < 60) setSavedAgo(`${secs}s ago`);
      else setSavedAgo(`${Math.round(secs / 60)}m ago`);
    };
    update();
    const t = setInterval(update, 5000);
    return () => clearInterval(t);
  }, [savedAt]);

  // Keyboard shortcuts.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement | null)?.tagName === 'INPUT') return;
      if (e.key === ' ') {
        e.preventDefault();
        setPlaying((p) => !p);
      }
      if (e.key.toLowerCase() === 's' && selectedClipId) {
        dispatch({ type: 'split', clipId: selectedClipId, at_s: playhead });
      }
      if (e.key === 'Backspace' && selectedClipId) {
        dispatch({ type: 'delete', clipId: selectedClipId });
        setSelectedClipId(null);
      }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z' && !e.shiftKey) {
        e.preventDefault();
        dispatch({ type: 'undo' });
      }
      if ((e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === 'y' || (e.key.toLowerCase() === 'z' && e.shiftKey))) {
        e.preventDefault();
        dispatch({ type: 'redo' });
      }
      // Arrow nudge — 0.1s, or 1s with shift.
      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
        e.preventDefault();
        const step = e.shiftKey ? 1 : 0.1;
        const dir = e.key === 'ArrowLeft' ? -1 : 1;
        setPlayhead((p) => Math.max(0, Math.min(history.present.duration_s, p + dir * step)));
      }
      // Home / End jump to start / end.
      if (e.key === 'Home') {
        e.preventDefault();
        setPlayhead(0);
      }
      if (e.key === 'End') {
        e.preventDefault();
        setPlayhead(history.present.duration_s);
      }
      // Shortcut overlay toggle (and close with Escape).
      if (e.key === '?' || (e.shiftKey && e.key === '/')) {
        e.preventDefault();
        setShortcutsOpen((v) => !v);
      }
      if (e.key === 'Escape') {
        setShortcutsOpen(false);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [playhead, selectedClipId, history.present.duration_s]);

  const onRender = async () => {
    if (!episodeId) return;
    setRendering(true);
    try {
      await editorApi.render(episodeId);
      toast.success('Render started', {
        description: 'Watch the Jobs page for progress. The episode will update when done.',
      });
      navigate(`/episodes/${episodeId}`);
    } catch (err) {
      toast.error('Render failed to start', { description: formatError(err) });
    } finally {
      setRendering(false);
    }
  };

  const timeline = history.present;

  const selectedClip = useMemo(() => {
    if (!selectedClipId) return null;
    for (const t of timeline.tracks) {
      for (const c of t.clips) {
        if (c.id === selectedClipId) return c;
      }
    }
    return null;
  }, [timeline, selectedClipId]);

  // Helpers that the tools rail + timeline drops both call so a
  // click and a drag produce identical overlays.
  const addTextOverlay = useCallback(
    (preset: 'title' | 'subtitle' | 'caption' | 'lowerThird') => {
      const style = {
        title: { text: 'Title', font_size: 80, y: 'h/2-h/8' },
        subtitle: { text: 'Subtitle', font_size: 56, y: 'h/2' },
        caption: { text: 'Caption text', font_size: 40, y: 'h-200' },
        lowerThird: { text: 'Lower third', font_size: 48, y: 'h-120' },
      }[preset];
      const id = `t-${Date.now()}`;
      dispatch({
        type: 'add_overlay',
        clip: {
          id,
          kind: 'text',
          text: style.text,
          font_size: style.font_size,
          color: '#ffffff',
          box: preset === 'caption' || preset === 'lowerThird',
          box_color: '#000000',
          x: '(w-text_w)/2',
          y: style.y,
          in_s: 0,
          out_s: Math.min(3, history.present.duration_s),
          start_s: playhead,
          end_s: Math.min(playhead + 3, history.present.duration_s),
        },
      });
      setSelectedClipId(id);
    },
    [dispatch, history.present.duration_s, playhead],
  );

  const addShapeOverlay = useCallback(
    (shape: 'rect' | 'circle' | 'line') => {
      // The serialized timeline only knows ``rect`` / ``circle``, so a
      // user-facing "line" choice is just a thin horizontal rect.
      const isLine = shape === 'line';
      const id = `s-${Date.now()}`;
      dispatch({
        type: 'add_overlay',
        clip: {
          id,
          kind: 'shape',
          shape: isLine ? 'rect' : shape,
          color: '#ffffff',
          w: isLine ? 800 : shape === 'circle' ? 200 : 400,
          h: isLine ? 4 : shape === 'circle' ? 200 : 200,
          x: '(w-w)/2',
          y: isLine ? 'h-320' : 'h/2-h/4',
          in_s: 0,
          out_s: 3,
          start_s: playhead,
          end_s: Math.min(playhead + 3, history.present.duration_s),
        },
      });
      setSelectedClipId(id);
    },
    [dispatch, history.present.duration_s, playhead],
  );

  const addImageOverlayFromAsset = useCallback(
    async (assetId: string, startSecs?: number) => {
      try {
        const asset = await assetsApi.get(assetId);
        const start = startSecs !== undefined ? startSecs : playhead;
        const clipId = `i-${Date.now()}`;
        dispatch({
          type: 'add_overlay',
          clip: {
            id: clipId,
            kind: 'image',
            asset_path: asset.file_path,
            x: '(W-w)/2',
            y: 'H-h-80',
            in_s: 0,
            out_s: 3,
            start_s: snap(start),
            end_s: Math.min(snap(start) + 3, history.present.duration_s),
          },
        });
        setSelectedClipId(clipId);
      } catch (err) {
        toast.error('Failed to attach asset', {
          description: err instanceof Error ? err.message : 'Unknown error',
        });
      }
    },
    [dispatch, history.present.duration_s, playhead, snap, toast],
  );

  // Drop a bundled stamp onto the timeline. Resolves the catalog entry
  // and adds an image overlay using the stamp's static URL — no
  // upload pipeline involved, so this is fast and reliable even on
  // air-gapped installs.
  const addStampOverlay = useCallback(
    (stampId: string, startSecs?: number) => {
      const stamp = findStampById(stampId);
      if (!stamp) {
        toast.error('Unknown stamp', { description: stampId });
        return;
      }
      const start = startSecs !== undefined ? startSecs : playhead;
      const dur = stamp.defaultDurationSeconds ?? 3;
      const clipId = `stamp-${Date.now()}`;
      dispatch({
        type: 'add_overlay',
        clip: {
          id: clipId,
          kind: 'image',
          // Pass the bundled URL through unchanged. The FFmpeg
          // overlay renderer can fetch http(s) URLs as well as
          // local paths, so this works in both dev and prod.
          asset_path: stamp.url,
          x: stamp.category === 'transitions' ? '0' : '(W-w)/2',
          y: stamp.category === 'lower-thirds'
            ? 'H-h-80'
            : stamp.category === 'transitions'
              ? '0'
              : '(H-h)/2',
          in_s: 0,
          out_s: dur,
          start_s: snap(start),
          end_s: Math.min(snap(start) + dur, history.present.duration_s),
        },
      });
      setSelectedClipId(clipId);
    },
    [dispatch, history.present.duration_s, playhead, snap, toast],
  );

  if (loading || !episodeId) {
    return (
      <div className="flex justify-center py-20">
        <Spinner size="lg" />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* ═══════════════════════════════════════════════════════════
          Top bar — compact, icon-heavy, full width
          ═══════════════════════════════════════════════════════════ */}
      <header className="h-12 border-b border-border flex items-center gap-2 px-3 shrink-0 bg-bg-surface">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => navigate(`/episodes/${episodeId}`)}
          title="Back to episode"
        >
          <ArrowLeft className="w-4 h-4" />
        </Button>
        <div className="h-6 w-px bg-border" />
        <h1 className="text-sm font-semibold">Video Editor</h1>
        <div className="flex-1" />

        {/* Autosave */}
        <div
          className={[
            'flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium',
            saving
              ? 'bg-warning/10 text-warning border border-warning/30'
              : savedAt
                ? 'bg-success/10 text-success border border-success/30'
                : 'bg-bg-elevated text-txt-muted border border-white/[0.06]',
          ].join(' ')}
          title="Autosave status"
        >
          <span
            className={[
              'w-1.5 h-1.5 rounded-full',
              saving
                ? 'bg-warning animate-pulse'
                : savedAt
                  ? 'bg-success'
                  : 'bg-txt-muted',
            ].join(' ')}
          />
          {saving ? 'Saving…' : savedAt ? `Saved ${savedAgo}` : 'Ready'}
        </div>

        <div className="h-6 w-px bg-border mx-1" />
        <Button
          variant="ghost"
          size="sm"
          onClick={() => dispatch({ type: 'undo' })}
          disabled={!history.past.length}
          title="Undo (⌘Z)"
        >
          <Undo2 className="w-4 h-4" />
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => dispatch({ type: 'redo' })}
          disabled={!history.future.length}
          title="Redo (⌘⇧Z)"
        >
          <Redo2 className="w-4 h-4" />
        </Button>
        <div className="h-6 w-px bg-border mx-1" />
        <Button
          variant="ghost"
          size="sm"
          onClick={async () => {
            if (!episodeId) return;
            setPreviewingProxy(true);
            try {
              await editorApi.preview(episodeId);
              setTimeout(() => setProxyReadyTs(Date.now()), 30_000);
              toast.success('Preview render enqueued', {
                description:
                  'Proxy will swap in once FFmpeg finishes (~30s).',
              });
            } catch (err) {
              toast.error('Preview failed', {
                description: formatError(err),
              });
            } finally {
              setPreviewingProxy(false);
            }
          }}
          disabled={previewingProxy}
          title="Render a fast 480p proxy with overlays + envelope mixed in"
        >
          {previewingProxy ? 'Preview…' : 'Preview'}
        </Button>
        <Button
          variant="primary"
          size="sm"
          onClick={() => void onRender()}
          disabled={rendering}
        >
          <Rocket className="w-4 h-4 mr-1" />
          {rendering ? 'Rendering…' : 'Render'}
        </Button>
      </header>

      {/* ═══════════════════════════════════════════════════════════
          Body — 3-column: ToolsRail | main | RightPanel
          ═══════════════════════════════════════════════════════════ */}
      <div className="flex-1 flex min-h-0">
        {/* Tools rail */}
        <ToolsRail
          onAddText={addTextOverlay}
          onAddShape={addShapeOverlay}
          onOpenAssetsTab={() => setRightPanelTab('assets')}
          onOpenStampsTab={() => setRightPanelTab('stamps')}
          onSplit={() => {
            if (selectedClipId) {
              dispatch({
                type: 'split',
                clipId: selectedClipId,
                at_s: playhead,
              });
            }
          }}
          onDelete={() => {
            if (selectedClipId) {
              dispatch({ type: 'delete', clipId: selectedClipId });
              setSelectedClipId(null);
            }
          }}
          snapEnabled={snapEnabled}
          snapStep={snapStep}
          onToggleSnap={() => setSnapEnabled((v) => !v)}
          onZoomIn={() => setZoom((z) => Math.min(240, z + 20))}
          onZoomOut={() => setZoom((z) => Math.max(20, z - 20))}
          onOpenShortcuts={() => setShortcutsOpen(true)}
          hasSelection={!!selectedClipId}
        />

        {/* Center column: preview on top, draggable splitter, timeline
            below. The split is user-resizable and stored in local
            storage so the next visit remembers it. The preview
            container uses ``aspectRatio`` + ``maxHeight: 100%`` so
            the video scales to fit without pushing into the
            timeline, regardless of viewport height. */}
        <div
          ref={splitContainerRef}
          className="flex-1 flex flex-col min-w-0 border-r border-border"
          onMouseMove={(e) => {
            if (!draggingSplit.current || !splitContainerRef.current) return;
            const rect = splitContainerRef.current.getBoundingClientRect();
            const local = e.clientY - rect.top;
            const pct = (local / rect.height) * 100;
            // Clamp 25–80% so neither half collapses entirely.
            setPreviewPct(Math.min(80, Math.max(25, pct)));
          }}
          onMouseUp={() => {
            if (draggingSplit.current) {
              draggingSplit.current = false;
              document.body.style.cursor = '';
              document.body.style.userSelect = '';
            }
          }}
          onMouseLeave={() => {
            if (draggingSplit.current) {
              draggingSplit.current = false;
              document.body.style.cursor = '';
              document.body.style.userSelect = '';
            }
          }}
        >
          {/* Preview — height driven by the user-resizable split. The
              inner box uses CSS aspect-ratio + max constraints so the
              video always fits the available space (no overflow into
              the timeline). */}
          <div
            className="min-h-0 flex items-center justify-center bg-black/40 p-3 relative"
            style={{ height: `${previewPct}%` }}
          >
            <PreviewPlayer
              timeline={timeline}
              playhead={playhead}
              onPlayheadChange={setPlayhead}
              playing={playing}
              onPlayToggle={() => setPlaying((p) => !p)}
              proxyUrl={
                proxyReadyTs
                  ? `/storage/episodes/${episodeId}/output/proxy.mp4?v=${proxyReadyTs}`
                  : null
              }
              finalVideoUrl={
                session?.final_video_path
                  ? `/storage/${session.final_video_path}`
                  : null
              }
              aspectRatio={previewAspect}
              onAspectDetected={setPreviewAspect}
            />
            {/* Reset-split button — quick way back to the default if
                the user has dragged into a corner. Sits in the
                bottom-right of the preview area. */}
            <button
              type="button"
              onClick={() => setPreviewPct(58)}
              className="absolute bottom-2 right-2 rounded bg-bg-elevated/80 border border-border px-2 py-0.5 text-[10px] text-txt-tertiary hover:text-txt-primary hover:border-accent/40 transition-colors duration-fast backdrop-blur-sm"
              title="Reset preview / timeline split"
            >
              Fit
            </button>
          </div>

          {/* Splitter handle — drag to resize. Visual indicator on
              hover; cursor swaps to row-resize. */}
          <div
            role="separator"
            aria-orientation="horizontal"
            aria-label="Resize preview and timeline"
            tabIndex={0}
            onMouseDown={(e) => {
              draggingSplit.current = true;
              document.body.style.cursor = 'row-resize';
              document.body.style.userSelect = 'none';
              e.preventDefault();
            }}
            onKeyDown={(e) => {
              if (e.key === 'ArrowUp') {
                e.preventDefault();
                setPreviewPct((p) => Math.max(25, p - 2));
              } else if (e.key === 'ArrowDown') {
                e.preventDefault();
                setPreviewPct((p) => Math.min(80, p + 2));
              }
            }}
            className="h-1.5 bg-border hover:bg-accent/40 active:bg-accent transition-colors duration-fast cursor-row-resize relative shrink-0 group focus:outline-none focus:bg-accent/40"
          >
            <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-10 h-0.5 bg-txt-muted/50 group-hover:bg-accent rounded-full pointer-events-none" />
          </div>

          {/* Timeline strip — fills the remaining column space below
              the splitter. min-h prevents collapse to zero when the
              user drags the split handle hard. */}
          <div
            className="flex-1 min-h-[180px] border-t border-border bg-bg-surface flex flex-col"
          >
            {/* Mini controls bar above the tracks */}
            <div className="h-9 px-3 flex items-center gap-2 shrink-0 border-b border-border">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setPlaying((p) => !p)}
                title="Play / Pause (Space)"
              >
                {playing ? (
                  <Pause className="w-4 h-4" />
                ) : (
                  <Play className="w-4 h-4" />
                )}
              </Button>
              <div className="text-xs font-mono text-txt-muted w-32 tabular-nums">
                {playhead.toFixed(2)}s / {timeline.duration_s.toFixed(2)}s
              </div>
              <div className="flex-1" />
              <div className="text-[10px] text-txt-muted hidden md:flex items-center gap-1">
                <MoveHorizontal size={10} />
                Drag assets into the timeline to add overlays
              </div>
            </div>

            {/* Tracks — horizontally scrollable, vertically snug */}
            <div
              className="flex-1 overflow-auto"
              onDragOver={(e) => {
                if (
                  e.dataTransfer.types.includes(ASSET_DRAG_MIME) ||
                  e.dataTransfer.types.includes(STAMP_DRAG_MIME)
                ) {
                  e.preventDefault();
                  e.dataTransfer.dropEffect = 'copy';
                }
              }}
              onDrop={(e) => {
                const assetId = e.dataTransfer.getData(ASSET_DRAG_MIME);
                const stampId = e.dataTransfer.getData(STAMP_DRAG_MIME);
                if (!assetId && !stampId) return;
                e.preventDefault();
                // Map the drop x-position (relative to the scrollable
                // container's left edge plus its horizontal scroll
                // offset) into timeline seconds.
                const target = e.currentTarget as HTMLDivElement;
                const rect = target.getBoundingClientRect();
                const localX = e.clientX - rect.left + target.scrollLeft;
                // The track container reserves ~80px on the left for
                // labels before the zoomed timeline area begins.
                const xInTimeline = Math.max(0, localX - 80);
                const dropSecs = xInTimeline / zoom;
                if (stampId) {
                  addStampOverlay(stampId, dropSecs);
                } else if (assetId) {
                  void addImageOverlayFromAsset(assetId, dropSecs);
                }
              }}
            >
              <div
                style={{
                  minWidth: Math.max(timeline.duration_s * zoom + 80, 600),
                }}
                className="p-3"
              >
                <TimelineRuler
                  duration={timeline.duration_s}
                  zoom={zoom}
                  playhead={playhead}
                  onScrub={(t) => setPlayhead(snap(t))}
                />
                <div className="space-y-2 mt-1">
                  {timeline.tracks.map((track) => (
                    <TrackRow
                      key={track.id}
                      track={track}
                      zoom={zoom}
                      duration={timeline.duration_s}
                      playhead={playhead}
                      onScrub={(t) => setPlayhead(snap(t))}
                      selectedClipId={selectedClipId}
                      onSelectClip={setSelectedClipId}
                      onReorder={(from, to) =>
                        dispatch({
                          type: 'reorder',
                          trackId: track.id,
                          fromIndex: from,
                          toIndex: to,
                        })
                      }
                      onTrim={(id, in_s, out_s) =>
                        dispatch({
                          type: 'trim',
                          clipId: id,
                          in_s: in_s === undefined ? undefined : snap(in_s),
                          out_s:
                            out_s === undefined ? undefined : snap(out_s),
                        })
                      }
                      onEnvelope={(clipId, envelope) =>
                        dispatch({
                          type: 'envelope',
                          trackId: track.id,
                          clipId,
                          envelope,
                        })
                      }
                      waveformUrl={waveformUrlFor(episodeId, track.id)}
                    />
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Right panel: Inspector / Captions / Assets */}
        <RightPanel
          activeTab={inspectorTab}
          onTabChange={setInspectorTab}
          episodeId={episodeId}
          playhead={playhead}
          selectedClip={selectedClip}
          onUpdateOverlay={(patch) => {
            if (!selectedClip) return;
            dispatch({
              type: 'update_overlay',
              clipId: selectedClip.id,
              patch,
            });
          }}
          onDeleteClip={() => {
            if (!selectedClip) return;
            dispatch({ type: 'delete', clipId: selectedClip.id });
            setSelectedClipId(null);
          }}
          onTrimClip={(in_s, out_s) => {
            if (!selectedClip) return;
            dispatch({
              type: 'trim',
              clipId: selectedClip.id,
              in_s,
              out_s,
            });
          }}
          onPickAsset={(id) => void addImageOverlayFromAsset(id)}
          onPickStamp={(id) => addStampOverlay(id)}
          initialTab={rightPanelTab}
        />
      </div>

      {shortcutsOpen && (
        <div
          className="fixed inset-0 z-[9998] flex items-center justify-center bg-black/60 backdrop-blur-sm"
          onClick={() => setShortcutsOpen(false)}
          role="dialog"
          aria-label="Keyboard shortcuts"
        >
          <div
            className="bg-bg-elevated border border-border rounded-xl p-6 max-w-md w-[92%] shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-display text-base">Keyboard shortcuts</h3>
              <button
                onClick={() => setShortcutsOpen(false)}
                className="text-txt-tertiary hover:text-txt-primary text-lg"
                aria-label="Close"
              >
                ×
              </button>
            </div>
            <div className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-xs">
              <kbd className="kbd">Space</kbd>
              <span>Play / pause</span>
              <kbd className="kbd">←</kbd>
              <span>Nudge playhead -0.1s (Shift = -1s)</span>
              <kbd className="kbd">→</kbd>
              <span>Nudge playhead +0.1s (Shift = +1s)</span>
              <kbd className="kbd">Home</kbd>
              <span>Jump to start</span>
              <kbd className="kbd">End</kbd>
              <span>Jump to end</span>
              <kbd className="kbd">S</kbd>
              <span>Split selected clip at playhead</span>
              <kbd className="kbd">⌫</kbd>
              <span>Delete selected clip</span>
              <kbd className="kbd">⌘/Ctrl + Z</kbd>
              <span>Undo (up to 200 steps)</span>
              <kbd className="kbd">⌘/Ctrl + ⇧ Z</kbd>
              <span>Redo</span>
              <kbd className="kbd">?</kbd>
              <span>Toggle this overlay</span>
              <kbd className="kbd">Esc</kbd>
              <span>Close overlay</span>
            </div>
            <p className="text-[11px] text-txt-tertiary mt-4">
              Snap-to-grid is {snapEnabled ? `on at ${snapStep}s` : 'off'}; toggle with the
              Snap button in the toolbar. Grid step shrinks as you zoom in.
            </p>
          </div>
        </div>
      )}

      <AssetPicker
        open={assetPickerOpen}
        onClose={() => setAssetPickerOpen(false)}
        kind="image"
        multi={false}
        title="Add image overlay"
        onSelect={async (assetIds) => {
          setAssetPickerOpen(false);
          const id = assetIds[0];
          if (!id) return;
          try {
            const asset = await assetsApi.get(id);
            const clipId = `i-${Date.now()}`;
            dispatch({
              type: 'add_overlay',
              clip: {
                id: clipId,
                kind: 'image',
                asset_path: asset.file_path,
                x: '(W-w)/2',
                y: 'H-h-80',
                in_s: 0,
                out_s: 3,
                start_s: playhead,
                end_s: Math.min(playhead + 3, timeline.duration_s),
              },
            });
            setSelectedClipId(clipId);
          } catch (err) {
            toast.error('Failed to attach asset', {
              description: err instanceof Error ? err.message : 'Unknown error',
            });
          }
        }}
      />
    </div>
  );
}
