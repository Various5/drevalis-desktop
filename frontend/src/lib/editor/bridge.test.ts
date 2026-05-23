import { describe, it, expect } from 'vitest';
import { editTimelineToProject, projectToEditTimeline, mediaUrl } from './bridge';
import { type EditTimeline } from '@/lib/api';
import { type ProjectTimeline } from './timeline';

const backend: EditTimeline = {
  duration_s: 4,
  tracks: [
    {
      id: 'video',
      kind: 'video',
      clips: [
        { id: 'v-1', scene_number: 1, source: 'scene', asset_path: 'episodes/e/scenes/1.mp4', in_s: 0, out_s: 2, start_s: 0, end_s: 2, speed: 1 },
      ],
    },
    {
      id: 'voice',
      kind: 'audio',
      clips: [{ id: 'voice-main', asset_path: 'episodes/e/voice/v.wav', in_s: 0, out_s: 4, start_s: 0, end_s: 4, gain_db: 0 }],
    },
    {
      id: 'captions',
      kind: 'captions',
      // text is a backend caption field not on the strict type — cast.
      clips: [{ id: 'c1', in_s: 0, out_s: 1, start_s: 0, end_s: 1, ...( { text: 'Hi there' } as object) } as EditTimeline['tracks'][number]['clips'][number]],
    },
  ],
};

describe('editTimelineToProject', () => {
  it('maps tracks, kinds, and seconds→frames at 30fps', () => {
    const pt = editTimelineToProject(backend);
    expect(pt.fps).toBe(30);
    expect(pt.tracks.map((t) => t.kind)).toEqual(['video', 'audio', 'caption']);
    const v = pt.tracks[0]!.clips[0]!;
    expect(v.sourceId).toBe('episodes/e/scenes/1.mp4');
    expect([v.startFrame, v.endFrame, v.inFrame, v.outFrame]).toEqual([0, 60, 0, 60]);
    expect(pt.tracks[1]!.clips[0]!.data?.gainDb).toBe(0);
    expect(pt.tracks[2]!.clips[0]!.data?.caption).toEqual({ text: 'Hi there' });
  });

  it('honours a stashed fps over the default', () => {
    const pt = editTimelineToProject({ ...backend, fps: 60 } as EditTimeline);
    expect(pt.fps).toBe(60);
    expect(pt.tracks[0]!.clips[0]!.endFrame).toBe(120); // 2s * 60
  });
});

describe('round-trip backend → NLE → backend', () => {
  it('preserves canonical fields + backend-only extras', () => {
    const back = projectToEditTimeline(editTimelineToProject(backend));
    const v = back.tracks[0]!.clips[0]!;
    expect(v.asset_path).toBe('episodes/e/scenes/1.mp4');
    expect(v.scene_number).toBe(1); // preserved via passthrough
    expect(v.source).toBe('scene');
    expect([v.start_s, v.end_s, v.in_s, v.out_s]).toEqual([0, 2, 0, 2]);
    expect(back.tracks[2]!.kind).toBe('captions');
    expect(back.tracks[2]!.clips[0]!.text).toBe('Hi there');
  });
});

describe('round-trip NLE → backend → NLE', () => {
  it('preserves NLE-only fades / transform / filters', () => {
    const pt: ProjectTimeline = {
      fps: 30,
      tracks: [
        {
          id: 'video',
          kind: 'video',
          name: 'Video',
          locked: false,
          muted: false,
          solo: false,
          clips: [
            {
              id: 'a',
              trackId: 'video',
              kind: 'video',
              sourceId: 'episodes/e/scenes/1.mp4',
              inFrame: 0,
              outFrame: 60,
              startFrame: 0,
              endFrame: 60,
              fadeInFrames: 15,
              fadeOutFrames: 10,
              data: { transform: { scale: 1.5 }, filters: { brightness: 1.2 } },
            },
          ],
        },
      ],
    };
    const round = editTimelineToProject(projectToEditTimeline(pt));
    const c = round.tracks[0]!.clips[0]!;
    expect(c.fadeInFrames).toBe(15);
    expect(c.fadeOutFrames).toBe(10);
    expect(c.data?.transform).toEqual({ scale: 1.5 });
    expect(c.data?.filters).toEqual({ brightness: 1.2 });
  });
});

describe('mediaUrl', () => {
  it('builds a same-origin /storage URL', () => {
    expect(mediaUrl('episodes/e/scenes/1.mp4')).toBe('/storage/episodes/e/scenes/1.mp4');
    expect(mediaUrl('/episodes/e/x.mp4')).toBe('/storage/episodes/e/x.mp4');
  });
});
