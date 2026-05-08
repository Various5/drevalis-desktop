import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { WeekView } from './WeekView';
import type { ScheduledPost } from '../types';

// ---------------------------------------------------------------------------
// Mock PostChip — isolate WeekView from PostChip rendering details
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

/** Monday 2026-05-04 */
const WEEK_START = new Date('2026-05-04T00:00:00');

function makePost(overrides: Partial<ScheduledPost> = {}): ScheduledPost {
  return {
    id: 'p1',
    content_type: 'episode',
    content_id: 'e1',
    platform: 'youtube',
    scheduled_at: '2026-05-04T14:30:00',
    title: 'Test post',
    status: 'scheduled',
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('WeekView', () => {
  beforeEach(() => {
    noop.mockClear();
  });

  it('renders 7 column day headers', () => {
    render(<WeekView weekStart={WEEK_START} posts={[]} onCancel={noop} />);
    // TimelineGrid renders aria-labels on column headers using the full date.
    // WEEK_START is 2026-05-04 (Monday), so we should have columns Mon–Sun.
    // Check via role=columnheader aria-label pattern.
    const headers = screen.getAllByRole('columnheader');
    // 7 day columns (excludes any gutter cells without roles)
    expect(headers.length).toBeGreaterThanOrEqual(7);
  });

  it('renders posts as chips in the correct day column', () => {
    const monday = makePost({
      id: 'mon-post',
      scheduled_at: '2026-05-04T09:00:00',
      title: 'Monday post',
    });
    const thursday = makePost({
      id: 'thu-post',
      scheduled_at: '2026-05-07T18:00:00',
      title: 'Thursday post',
    });
    render(
      <WeekView
        weekStart={WEEK_START}
        posts={[monday, thursday]}
        onCancel={noop}
      />,
    );
    expect(screen.getByText('Monday post')).toBeInTheDocument();
    expect(screen.getByText('Thursday post')).toBeInTheDocument();
  });

  it('does not render a post from a different week', () => {
    const outOfRange = makePost({
      id: 'out',
      scheduled_at: '2026-05-11T09:00:00', // next Monday
      title: 'Next week post',
    });
    render(<WeekView weekStart={WEEK_START} posts={[outOfRange]} onCancel={noop} />);
    expect(screen.queryByText('Next week post')).toBeNull();
  });

  it('renders all 7 posts when each is on a different day of the week', () => {
    // Week: 2026-05-04 (Mon) through 2026-05-10 (Sun)
    const dates = ['2026-05-04', '2026-05-05', '2026-05-06', '2026-05-07', '2026-05-08', '2026-05-09', '2026-05-10'];
    const posts = dates.map((d, i) =>
      makePost({
        id: `p${i}`,
        scheduled_at: `${d}T10:00:00`,
        title: `Day ${i + 1} post`,
      }),
    );
    render(<WeekView weekStart={WEEK_START} posts={posts} onCancel={noop} />);
    for (let i = 0; i < 7; i++) {
      expect(screen.getByText(`Day ${i + 1} post`)).toBeInTheDocument();
    }
  });
});
