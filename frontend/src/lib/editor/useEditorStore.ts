/**
 * useEditorStore — the React bridge for the NLE (Phase 2, PR 3 — ADR 002).
 *
 * Holds the timeline behind the undo/redo history, plus transient UI state
 * (selection, playhead frame), and exposes typed action methods that wrap the
 * pure operations in `operations.ts`. Components bind to this; the operations
 * and history stay pure + independently tested.
 */

import { useCallback, useMemo, useReducer } from 'react';
import { type ProjectTimeline, type ClipTransform, type ClipFilters } from './timeline';
import {
  type History,
  initHistory,
  commit,
  undo as undoHistory,
  redo as redoHistory,
  canUndo,
  canRedo,
} from './history';
import * as ops from './operations';

interface State {
  history: History<ProjectTimeline>;
  selectedClipId: string | null;
  frame: number;
}

type Action =
  | { type: 'commit'; next: ProjectTimeline }
  | { type: 'undo' }
  | { type: 'redo' }
  | { type: 'select'; clipId: string | null }
  | { type: 'setFrame'; frame: number }
  | { type: 'load'; timeline: ProjectTimeline };

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case 'commit':
      return { ...state, history: commit(state.history, action.next) };
    case 'undo':
      return { ...state, history: undoHistory(state.history) };
    case 'redo':
      return { ...state, history: redoHistory(state.history) };
    case 'select':
      return { ...state, selectedClipId: action.clipId };
    case 'setFrame':
      return { ...state, frame: Math.max(0, Math.round(action.frame)) };
    case 'load':
      return { history: initHistory(action.timeline), selectedClipId: null, frame: 0 };
    default:
      return state;
  }
}

export interface EditorStore {
  timeline: ProjectTimeline;
  selectedClipId: string | null;
  frame: number;
  canUndo: boolean;
  canRedo: boolean;

  // history
  undo: () => void;
  redo: () => void;
  load: (timeline: ProjectTimeline) => void;

  // transient UI
  select: (clipId: string | null) => void;
  setFrame: (frame: number) => void;

  // timeline ops (each commits a new revision)
  moveClip: (clipId: string, startFrame: number) => void;
  trimStart: (clipId: string, startFrame: number) => void;
  trimEnd: (clipId: string, endFrame: number) => void;
  splitClip: (clipId: string, atFrame: number, newId: string) => void;
  bladeAll: (frame: number) => void;
  removeClip: (clipId: string) => void;
  rippleDelete: (clipId: string) => void;
  slip: (clipId: string, delta: number) => void;
  roll: (leftClipId: string, delta: number) => void;
  slide: (clipId: string, delta: number) => void;
  setClipSpeed: (clipId: string, speed: number) => void;
  setClipFade: (clipId: string, edge: 'in' | 'out', frames: number) => void;
  setClipTransform: (clipId: string, patch: Partial<ClipTransform>) => void;
  setClipFilters: (clipId: string, patch: Partial<ClipFilters>) => void;
  setTrackFlag: (trackId: string, flag: 'locked' | 'muted' | 'solo', value: boolean) => void;
  addMarker: (frame: number, note?: string) => void;
  removeMarker: (id: string) => void;
  updateMarkerNote: (id: string, note: string) => void;
}

export function useEditorStore(initial: ProjectTimeline): EditorStore {
  const [state, dispatch] = useReducer(reducer, undefined, () => ({
    history: initHistory(initial),
    selectedClipId: null,
    frame: 0,
  }));

  const timeline = state.history.present;

  // Apply a pure operation to the current timeline and commit the result.
  const apply = useCallback(
    (op: (tl: ProjectTimeline) => ProjectTimeline) => {
      dispatch({ type: 'commit', next: op(state.history.present) });
    },
    [state.history.present],
  );

  return useMemo<EditorStore>(
    () => ({
      timeline,
      selectedClipId: state.selectedClipId,
      frame: state.frame,
      canUndo: canUndo(state.history),
      canRedo: canRedo(state.history),

      undo: () => dispatch({ type: 'undo' }),
      redo: () => dispatch({ type: 'redo' }),
      load: (tl) => dispatch({ type: 'load', timeline: tl }),
      select: (clipId) => dispatch({ type: 'select', clipId }),
      setFrame: (frame) => dispatch({ type: 'setFrame', frame }),

      moveClip: (id, start) => apply((tl) => ops.moveClip(tl, id, start)),
      trimStart: (id, start) => apply((tl) => ops.trimClipStart(tl, id, start)),
      trimEnd: (id, end) => apply((tl) => ops.trimClipEnd(tl, id, end)),
      splitClip: (id, at, newId) => apply((tl) => ops.splitClip(tl, id, at, newId)),
      bladeAll: (frame) => apply((tl) => ops.splitAllAtFrame(tl, frame, () => crypto.randomUUID())),
      removeClip: (id) => apply((tl) => ops.removeClip(tl, id)),
      rippleDelete: (id) => apply((tl) => ops.rippleDelete(tl, id)),
      slip: (id, d) => apply((tl) => ops.slip(tl, id, d)),
      roll: (id, d) => apply((tl) => ops.roll(tl, id, d)),
      slide: (id, d) => apply((tl) => ops.slide(tl, id, d)),
      setClipSpeed: (id, speed) => apply((tl) => ops.setClipSpeed(tl, id, speed)),
      setClipFade: (id, edge, frames) => apply((tl) => ops.setClipFade(tl, id, edge, frames)),
      setClipTransform: (id, patch) => apply((tl) => ops.setClipTransform(tl, id, patch)),
      setClipFilters: (id, patch) => apply((tl) => ops.setClipFilters(tl, id, patch)),
      setTrackFlag: (trackId, flag, value) => apply((tl) => ops.setTrackFlag(tl, trackId, flag, value)),
      addMarker: (frame, note) => apply((tl) => ops.addMarker(tl, { id: crypto.randomUUID(), frame, note })),
      removeMarker: (id) => apply((tl) => ops.removeMarker(tl, id)),
      updateMarkerNote: (id, note) => apply((tl) => ops.updateMarkerNote(tl, id, note)),
    }),
    [timeline, state.selectedClipId, state.frame, state.history, apply],
  );
}
