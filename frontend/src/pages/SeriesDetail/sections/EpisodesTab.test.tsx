import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { EpisodesTab } from './EpisodesTab';
import type { EpisodeListItem } from '@/types';

// ---------------------------------------------------------------------------
// Mock EpisodeCard — avoids pulling in router-heavy deps transitively.
// ---------------------------------------------------------------------------

vi.mock('@/components/episodes/EpisodeCard', () => ({
  EpisodeCard: ({ episode }: { episode: EpisodeListItem }) => (
    <div data-testid="episode-card">{episode.title}</div>
  ),
}));

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeEpisode(
  overrides: Partial<EpisodeListItem> = {},
): EpisodeListItem {
  return {
    id: 'ep-1',
    series_id: 'series-1',
    title: 'Test Episode',
    topic: null,
    status: 'draft',
    metadata_: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}

const defaultHandlers = {
  onCreate: vi.fn(),
  onGenerateAllDrafts: vi.fn(),
  onAiAdd: vi.fn(),
  onTrending: vi.fn(),
  onDeleteAll: vi.fn(),
  generatingAllDrafts: false,
  addingEpisodesAi: false,
  trendingLoading: false,
};

function renderTab(
  episodes: EpisodeListItem[] = [],
  handlers: Partial<typeof defaultHandlers> = {},
) {
  return render(
    <MemoryRouter>
      <EpisodesTab episodes={episodes} {...defaultHandlers} {...handlers} />
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Reset mocks before each test
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// 1. Render — empty state
// ---------------------------------------------------------------------------

describe('EpisodesTab — empty state', () => {
  it('renders "No episodes" empty state when no episodes are given', () => {
    renderTab([]);
    expect(screen.getByText(/no episodes in this series/i)).toBeInTheDocument();
  });

  it('renders at least one "New Episode" button even when empty', () => {
    renderTab([]);
    const btns = screen.getAllByRole('button', { name: /new episode/i });
    expect(btns.length).toBeGreaterThan(0);
    expect(btns[0]).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// 2. Render — with episodes
// ---------------------------------------------------------------------------

describe('EpisodesTab — with episodes', () => {
  it('renders episode cards for each episode', () => {
    const eps = [
      makeEpisode({ id: 'ep-1', title: 'First Episode' }),
      makeEpisode({ id: 'ep-2', title: 'Second Episode', status: 'review' }),
    ];
    renderTab(eps);
    expect(screen.getAllByTestId('episode-card')).toHaveLength(2);
    expect(screen.getByText('First Episode')).toBeInTheDocument();
    expect(screen.getByText('Second Episode')).toBeInTheDocument();
  });

  it('shows episode count in the heading', () => {
    renderTab([makeEpisode(), makeEpisode({ id: 'ep-2', title: 'B' })]);
    expect(screen.getByText(/episodes \(2\)/i)).toBeInTheDocument();
  });

  it('shows "Generate N drafts" button when there are draft episodes', () => {
    renderTab([makeEpisode({ status: 'draft' })]);
    expect(
      screen.getByRole('button', { name: /generate 1 draft/i }),
    ).toBeInTheDocument();
  });

  it('does NOT show "Generate N drafts" button when there are no drafts', () => {
    renderTab([makeEpisode({ status: 'review' })]);
    expect(
      screen.queryByRole('button', { name: /generate/i }),
    ).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// 3. Action callbacks
// ---------------------------------------------------------------------------

describe('EpisodesTab — action callbacks', () => {
  it('calls onCreate when "New Episode" button is clicked', async () => {
    const onCreate = vi.fn();
    renderTab([], { onCreate });
    const btns = screen.getAllByRole('button', { name: /new episode/i });
    expect(btns.length).toBeGreaterThan(0);
    await userEvent.click(btns[0] as HTMLElement);
    expect(onCreate).toHaveBeenCalledTimes(1);
  });

  it('calls onAiAdd when "AI add 5" button is clicked', async () => {
    const onAiAdd = vi.fn();
    renderTab([], { onAiAdd });
    await userEvent.click(screen.getByRole('button', { name: /ai add 5/i }));
    expect(onAiAdd).toHaveBeenCalledTimes(1);
  });

  it('calls onTrending when "Trending" button is clicked', async () => {
    const onTrending = vi.fn();
    renderTab([], { onTrending });
    await userEvent.click(screen.getByRole('button', { name: /trending/i }));
    expect(onTrending).toHaveBeenCalledTimes(1);
  });

  it('calls onDeleteAll when "Delete All" button is clicked', async () => {
    const onDeleteAll = vi.fn();
    renderTab([makeEpisode()], { onDeleteAll });
    await userEvent.click(screen.getByRole('button', { name: /delete all/i }));
    expect(onDeleteAll).toHaveBeenCalledTimes(1);
  });

  it('calls onGenerateAllDrafts when "Generate N drafts" is clicked', async () => {
    const onGenerateAllDrafts = vi.fn();
    renderTab([makeEpisode({ status: 'draft' })], { onGenerateAllDrafts });
    await userEvent.click(
      screen.getByRole('button', { name: /generate 1 draft/i }),
    );
    expect(onGenerateAllDrafts).toHaveBeenCalledTimes(1);
  });
});

// ---------------------------------------------------------------------------
// 4. View toggle (kanban / grid)
// ---------------------------------------------------------------------------

describe('EpisodesTab — view toggle', () => {
  it('shows the kanban/grid toggle when there are episodes', () => {
    renderTab([makeEpisode()]);
    expect(screen.getByRole('button', { name: /kanban/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /grid/i })).toBeInTheDocument();
  });

  it('switches to grid view when Grid button is clicked', async () => {
    renderTab([makeEpisode()]);
    const gridBtn = screen.getByRole('button', { name: /grid/i });
    expect(gridBtn).toHaveAttribute('aria-pressed', 'false');
    await userEvent.click(gridBtn);
    expect(gridBtn).toHaveAttribute('aria-pressed', 'true');
  });
});
