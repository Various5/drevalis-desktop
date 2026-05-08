import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { PlatformTabs } from './PlatformTabs';
import type { ScheduledPost, PlatformFilter } from './types';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const noop = vi.fn();

function makePost(platform: string): ScheduledPost {
  return {
    id: `${platform}-1`,
    content_type: 'episode',
    content_id: 'e1',
    platform,
    scheduled_at: '2026-05-07T10:00:00',
    title: `${platform} post`,
    status: 'scheduled',
  };
}

function renderTabs(opts: {
  active?: PlatformFilter;
  posts?: ScheduledPost[];
  connected?: string[];
  youtubeConnected?: boolean;
  onChange?: (p: PlatformFilter) => void;
}) {
  const {
    active = 'all',
    posts = [],
    connected = [],
    youtubeConnected = false,
    onChange = noop,
  } = opts;
  return render(
    <PlatformTabs
      active={active}
      onChange={onChange}
      visiblePosts={posts}
      connectedSocials={connected}
      youtubeConnected={youtubeConnected}
    />,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('PlatformTabs', () => {
  beforeEach(() => {
    noop.mockClear();
  });

  it('always renders the "All" tab regardless of posts or connections', () => {
    renderTabs({ posts: [], connected: [], youtubeConnected: false });
    expect(screen.getByRole('tab', { name: 'All' })).toBeInTheDocument();
  });

  it('does not render platform tabs when no posts and no connected accounts', () => {
    renderTabs({ posts: [], connected: [], youtubeConnected: false });
    expect(screen.queryByRole('tab', { name: 'YouTube' })).toBeNull();
    expect(screen.queryByRole('tab', { name: 'TikTok' })).toBeNull();
  });

  it('renders a platform tab when there is a post for that platform', () => {
    renderTabs({ posts: [makePost('tiktok')] });
    expect(screen.getByRole('tab', { name: 'TikTok' })).toBeInTheDocument();
  });

  it('renders YouTube tab when youtubeConnected is true even without posts', () => {
    renderTabs({ posts: [], youtubeConnected: true });
    expect(screen.getByRole('tab', { name: 'YouTube' })).toBeInTheDocument();
  });

  it('renders social platform tabs when user has connected accounts', () => {
    renderTabs({ posts: [], connected: ['instagram', 'facebook'] });
    expect(screen.getByRole('tab', { name: 'Instagram' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Facebook' })).toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: 'TikTok' })).toBeNull();
  });

  it('renders tab for each platform with posts in range', () => {
    const posts = [makePost('youtube'), makePost('tiktok'), makePost('x')];
    renderTabs({ posts });
    expect(screen.getByRole('tab', { name: 'YouTube' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'TikTok' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'X (Twitter)' })).toBeInTheDocument();
  });

  it('marks the active tab with aria-selected="true"', () => {
    renderTabs({ active: 'youtube', posts: [makePost('youtube')] });
    const ytTab = screen.getByRole('tab', { name: 'YouTube' });
    expect(ytTab).toHaveAttribute('aria-selected', 'true');
    const allTab = screen.getByRole('tab', { name: 'All' });
    expect(allTab).toHaveAttribute('aria-selected', 'false');
  });

  it('calls onChange with "all" when the All tab is clicked', async () => {
    const onChange = vi.fn();
    renderTabs({
      active: 'youtube',
      posts: [makePost('youtube')],
      onChange,
    });
    await userEvent.click(screen.getByRole('tab', { name: 'All' }));
    expect(onChange).toHaveBeenCalledWith('all');
  });

  it('calls onChange with the platform when a platform tab is clicked', async () => {
    const onChange = vi.fn();
    renderTabs({ posts: [makePost('tiktok')], onChange });
    await userEvent.click(screen.getByRole('tab', { name: 'TikTok' }));
    expect(onChange).toHaveBeenCalledWith('tiktok');
  });

  it('deduplicates platforms — shows one tab per platform even with multiple posts', () => {
    const posts = [makePost('instagram'), makePost('instagram'), makePost('instagram')];
    renderTabs({ posts });
    const igTabs = screen.getAllByRole('tab', { name: 'Instagram' });
    expect(igTabs).toHaveLength(1);
  });
});
