import { describe, it, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useEditorStore } from './useEditorStore';
import { type ProjectTimeline } from './timeline';

function sample(): ProjectTimeline {
  return {
    fps: 30,
    tracks: [
      {
        id: 'v',
        kind: 'video',
        name: 'V',
        locked: false,
        muted: false,
        solo: false,
        clips: [
          { id: 'c0', trackId: 'v', kind: 'video', sourceId: 's0', inFrame: 0, outFrame: 30, startFrame: 0, endFrame: 30 },
          { id: 'c1', trackId: 'v', kind: 'video', sourceId: 's1', inFrame: 0, outFrame: 30, startFrame: 30, endFrame: 60 },
        ],
      },
    ],
  };
}

const startOf = (s: ProjectTimeline, id: string): number =>
  s.tracks[0]!.clips.find((c) => c.id === id)!.startFrame;

describe('useEditorStore', () => {
  it('applies an op and supports undo/redo', () => {
    const { result } = renderHook(() => useEditorStore(sample()));
    expect(result.current.canUndo).toBe(false);

    act(() => result.current.moveClip('c1', 100));
    expect(startOf(result.current.timeline, 'c1')).toBe(100);
    expect(result.current.canUndo).toBe(true);

    act(() => result.current.undo());
    expect(startOf(result.current.timeline, 'c1')).toBe(30);

    act(() => result.current.redo());
    expect(startOf(result.current.timeline, 'c1')).toBe(100);
  });

  it('tracks selection and a rounded playhead frame', () => {
    const { result } = renderHook(() => useEditorStore(sample()));
    act(() => result.current.select('c0'));
    expect(result.current.selectedClipId).toBe('c0');
    act(() => result.current.setFrame(42.6));
    expect(result.current.frame).toBe(43);
  });

  it('load resets history, selection, and playhead', () => {
    const { result } = renderHook(() => useEditorStore(sample()));
    act(() => result.current.moveClip('c1', 100));
    act(() => result.current.setFrame(50));
    act(() => result.current.load(sample()));
    expect(result.current.canUndo).toBe(false);
    expect(result.current.frame).toBe(0);
    expect(startOf(result.current.timeline, 'c1')).toBe(30);
  });

  it('splits a clip into two via the store', () => {
    const { result } = renderHook(() => useEditorStore(sample()));
    act(() => result.current.splitClip('c0', 10, 'c0b'));
    expect(result.current.timeline.tracks[0]!.clips).toHaveLength(3);
  });
});
