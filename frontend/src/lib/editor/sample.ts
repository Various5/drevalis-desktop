import { type ProjectTimeline, type Track, type Clip, type TrackKind } from './timeline';

/**
 * A representative sample timeline for the new editor's flagged dev route and
 * for demos. Six 4-second video shots, a voice track, and an intro overlay.
 * Real episode timelines load from the backend in a later PR (ADR 002).
 */
export function sampleTimeline(fps = 30): ProjectTimeline {
  const shot = 4 * fps;

  const video: Clip[] = Array.from({ length: 6 }, (_, i) => ({
    id: `v${i}`,
    trackId: 'V1',
    kind: 'video',
    sourceId: `scene-${i}`,
    inFrame: 0,
    outFrame: shot,
    startFrame: i * shot,
    endFrame: (i + 1) * shot,
  }));

  const overlays: Clip[] = [
    {
      id: 'o0',
      trackId: 'O1',
      kind: 'overlay',
      sourceId: null,
      inFrame: 0,
      outFrame: 2 * fps,
      startFrame: fps,
      endFrame: 3 * fps,
      data: { overlay: { overlay: 'text', text: 'Intro', box: [0.1, 0.8, 0.8, 0.12], color: '#ffffff', fontSize: 64 } },
    },
  ];

  const voice: Clip = {
    id: 'voice',
    trackId: 'A1',
    kind: 'audio',
    sourceId: 'voice',
    inFrame: 0,
    outFrame: 6 * shot,
    startFrame: 0,
    endFrame: 6 * shot,
    data: { gainDb: 0 },
  };

  const captions: Clip[] = [
    { text: 'Welcome to the show', at: 0 },
    { text: 'Here is the big idea', at: 2 },
    { text: 'And that is a wrap', at: 4 },
  ].map(({ text, at }, i) => ({
    id: `cap${i}`,
    trackId: 'C1',
    kind: 'caption',
    sourceId: null,
    inFrame: 0,
    outFrame: 2 * shot,
    startFrame: at * shot,
    endFrame: (at + 2) * shot,
    data: { caption: { text } },
  }));

  const mk = (id: string, kind: TrackKind, clips: Clip[]): Track => ({
    id,
    kind,
    name: id,
    locked: false,
    muted: false,
    solo: false,
    clips,
  });

  return {
    fps,
    tracks: [
      mk('V1', 'video', video),
      mk('A1', 'audio', [voice]),
      mk('C1', 'caption', captions),
      mk('O1', 'overlay', overlays),
    ],
    scenes: [
      { id: 'sc0', startFrame: 0, name: 'Cold open' },
      { id: 'sc1', startFrame: 2 * shot, name: 'Main point' },
      { id: 'sc2', startFrame: 4 * shot, name: 'Outro' },
    ],
  };
}
