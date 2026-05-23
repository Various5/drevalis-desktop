import { describe, it, expect } from 'vitest';
import { defaultMediaResolver } from './mediaSource';

describe('defaultMediaResolver', () => {
  it('resolves video extensions to a /storage video source', () => {
    expect(defaultMediaResolver('episodes/e/scenes/1.mp4')).toEqual({
      url: '/storage/episodes/e/scenes/1.mp4',
      kind: 'video',
    });
    expect(defaultMediaResolver('a/b.MOV')?.kind).toBe('video');
  });
  it('resolves image extensions to an image source', () => {
    expect(defaultMediaResolver('episodes/e/scenes/1.png')?.kind).toBe('image');
    expect(defaultMediaResolver('a/b.jpeg')?.kind).toBe('image');
  });
  it('returns null for ids that are not recognisable media (sample fakes)', () => {
    expect(defaultMediaResolver('scene-0')).toBeNull();
    expect(defaultMediaResolver('voice')).toBeNull();
  });
});
