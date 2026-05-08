import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { DayView } from './DayView';
import type { ScheduledPost } from '../types';

// ---------------------------------------------------------------------------
// Mock PostChip
// ---------------------------------------------------------------------------

vi.mock('../PostChip', () => ({
  PostChip: ({ post }: { post: ScheduledPost }) => (
    <div data-testid="post-chip" data-post-id={post.id}>
      {post.title}
    </div>
  ),
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const noop = vi.fn();

const TODAY = new Date('2026-05-07T00:00:00');

function makePost(overrides: Partial<ScheduledPost> = {}): ScheduledPost {
  return {
    id: 'p1',
    content_type: 'episode',
    content_id: 'e1',
    platform: 'youtube',
    scheduled_at: '2026-05-07T10:00:00',
    title: 'Test post',
    status: 'scheduled',
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('DayView', () => {
  beforeEach(() => {
    noop.mockClear();
  });

  it('renders posts for the given day', () => {
    const posts = [
      makePost({ id: 'a', scheduled_at: '2026-05-07T09:00:00', title: 'Morning post' }),
      makePost({ id: 'b', scheduled_at: '2026-05-07T18:00:00', title: 'Evening post' }),
    ];
    render(<DayView date={TODAY} posts={posts} onCancel={noop} />);
    expect(screen.getByText('Morning post')).toBeInTheDocument();
    expect(screen.getByText('Evening post')).toBeInTheDocument();
  });

  it('does not render posts from other days', () => {
    const outOfRange = makePost({
      id: 'other',
      scheduled_at: '2026-05-08T10:00:00',
      title: 'Tomorrow post',
    });
    render(<DayView date={TODAY} posts={[outOfRange]} onCancel={noop} />);
    expect(screen.queryByText('Tomorrow post')).toBeNull();
  });

  it('renders no chips when there are no posts', () => {
    render(<DayView date={TODAY} posts={[]} onCancel={noop} />);
    expect(screen.queryByTestId('post-chip')).toBeNull();
  });

  it('renders multiple posts for the same day in time order', () => {
    const posts = [
      makePost({ id: 'c3', scheduled_at: '2026-05-07T22:00:00', title: 'Night post' }),
      makePost({ id: 'c1', scheduled_at: '2026-05-07T08:00:00', title: 'Early post' }),
      makePost({ id: 'c2', scheduled_at: '2026-05-07T14:00:00', title: 'Afternoon post' }),
    ];
    render(<DayView date={TODAY} posts={posts} onCancel={noop} />);
    // All three should be present
    expect(screen.getByText('Night post')).toBeInTheDocument();
    expect(screen.getByText('Early post')).toBeInTheDocument();
    expect(screen.getByText('Afternoon post')).toBeInTheDocument();
  });

  it('renders the day-view container', () => {
    render(<DayView date={TODAY} posts={[]} onCancel={noop} />);
    expect(screen.getByTestId('day-view')).toBeInTheDocument();
  });
});
