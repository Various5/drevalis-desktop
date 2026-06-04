import { describe, it, expect } from 'vitest';
import { youtubeFingerprint } from './SocialConnectWizard';
import type { YouTubeChannel } from '@/types';

function channel(
  overrides: Partial<YouTubeChannel> & { id: string },
): YouTubeChannel {
  return {
    channel_id: `yt-${overrides.id}`,
    channel_name: 'Test channel',
    is_active: true,
    upload_days: null,
    upload_time: null,
    created_at: '2026-06-01T00:00:00Z',
    updated_at: '2026-06-01T00:00:00Z',
    ...overrides,
  };
}

describe('youtubeFingerprint', () => {
  it('changes when a brand-new channel is connected (a new id appears)', () => {
    const before = youtubeFingerprint([channel({ id: 'a' })]);
    const after = youtubeFingerprint([
      channel({ id: 'a' }),
      channel({ id: 'b' }),
    ]);
    expect(after).not.toBe(before);
  });

  it('changes when an existing channel is RECONNECTED (same id, bumped updated_at)', () => {
    // Regression guard: reconnecting a channel re-uses the same row, so the
    // id set is identical before and after. The pre-fix id-only fingerprint
    // never observed a change, leaving the connect wizard polling until its
    // 5-minute timeout even though the OAuth grant had landed. Keying on
    // updated_at (bumped by the callback's token write) is what makes the
    // reconnect detectable.
    const before = youtubeFingerprint([
      channel({ id: 'a', updated_at: '2026-06-01T00:00:00Z' }),
    ]);
    const after = youtubeFingerprint([
      channel({ id: 'a', updated_at: '2026-06-04T12:30:00Z' }),
    ]);
    expect(after).not.toBe(before);
  });

  it('is stable when nothing has changed', () => {
    const chans = [channel({ id: 'a' }), channel({ id: 'b' })];
    expect(youtubeFingerprint(chans)).toBe(youtubeFingerprint([...chans]));
  });

  it('is order-independent (sorted)', () => {
    const a = channel({ id: 'a', updated_at: '2026-06-01T00:00:00Z' });
    const b = channel({ id: 'b', updated_at: '2026-06-02T00:00:00Z' });
    expect(youtubeFingerprint([a, b])).toBe(youtubeFingerprint([b, a]));
  });

  it('treats an empty channel list as the empty fingerprint', () => {
    expect(youtubeFingerprint([])).toBe('');
  });
});
