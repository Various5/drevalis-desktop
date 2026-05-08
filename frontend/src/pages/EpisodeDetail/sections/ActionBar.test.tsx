import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { ActionBar } from './ActionBar';
import type { Episode, ProgressMessage } from '@/types';

// ---------------------------------------------------------------------------
// Navigation spy
// ---------------------------------------------------------------------------

const navigateSpy = vi.fn();

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>(
    'react-router-dom',
  );
  return { ...actual, useNavigate: () => navigateSpy };
});

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeEpisode(overrides: Partial<Episode> = {}): Episode {
  return {
    id: 'ep-1',
    series_id: 'series-1',
    title: 'Test Episode',
    topic: null,
    status: 'draft',
    script: null,
    base_path: null,
    generation_log: null,
    metadata_: null,
    override_voice_profile_id: null,
    override_llm_config_id: null,
    override_caption_style: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    media_assets: [],
    generation_jobs: [],
    ...overrides,
  };
}

const NO_PROGRESS: Record<string, ProgressMessage> = {};

const defaultProps = {
  action: 'idle' as const,
  mergedProgress: NO_PROGRESS,
  onGenerate: vi.fn(),
  onRetry: vi.fn(),
  onReassemble: vi.fn(),
  onRegenerateVoice: vi.fn(),
  onDuplicate: vi.fn(),
  onReset: vi.fn(),
  onOpenCancel: vi.fn(),
  onOpenDelete: vi.fn(),
};

function renderBar(episode: Episode, props: Partial<typeof defaultProps> = {}) {
  return render(
    <MemoryRouter>
      <ActionBar episode={episode} {...defaultProps} {...props} />
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Reset mocks before each test
// ---------------------------------------------------------------------------

beforeEach(() => {
  navigateSpy.mockClear();
  Object.values(defaultProps).forEach((v) => {
    if (typeof v === 'function') vi.mocked(v as ReturnType<typeof vi.fn>).mockClear?.();
  });
});

// ---------------------------------------------------------------------------
// 1. Primary action by status
// ---------------------------------------------------------------------------

describe('ActionBar — primary action by status', () => {
  it('shows Generate button for draft status', () => {
    renderBar(makeEpisode({ status: 'draft' }));
    expect(
      screen.getByRole('button', { name: /generate/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /retry generation/i }),
    ).toBeNull();
  });

  it('shows Retry generation button for failed status', () => {
    renderBar(makeEpisode({ status: 'failed' }));
    expect(
      screen.getByRole('button', { name: /retry generation/i }),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^generate$/i })).toBeNull();
  });

  it('shows Stop button for generating status', () => {
    renderBar(makeEpisode({ status: 'generating' }));
    expect(
      screen.getByRole('button', { name: /stop/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /^generate$/i }),
    ).toBeNull();
  });

  it('shows Regenerate dropdown for review status', () => {
    renderBar(makeEpisode({ status: 'review' }));
    expect(
      screen.getByRole('button', { name: /regenerate options/i }),
    ).toBeInTheDocument();
  });

  it('shows Regenerate dropdown for editing status', () => {
    renderBar(makeEpisode({ status: 'editing' }));
    expect(
      screen.getByRole('button', { name: /regenerate options/i }),
    ).toBeInTheDocument();
  });

  it('shows Regenerate dropdown for exported status', () => {
    renderBar(makeEpisode({ status: 'exported' }));
    expect(
      screen.getByRole('button', { name: /regenerate options/i }),
    ).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// 2. Generate button calls onGenerate without steps
// ---------------------------------------------------------------------------

describe('ActionBar — Generate button', () => {
  it('calls onGenerate when clicked from draft', async () => {
    const onGenerate = vi.fn();
    renderBar(makeEpisode({ status: 'draft' }), { onGenerate });
    await userEvent.click(screen.getByRole('button', { name: /generate/i }));
    expect(onGenerate).toHaveBeenCalledTimes(1);
    expect(onGenerate).toHaveBeenCalledWith(/* no args */ );
  });

  it('calls onRetry when Retry generation is clicked', async () => {
    const onRetry = vi.fn();
    renderBar(makeEpisode({ status: 'failed' }), { onRetry });
    await userEvent.click(
      screen.getByRole('button', { name: /retry generation/i }),
    );
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});

// ---------------------------------------------------------------------------
// 3. Stop button calls onOpenCancel
// ---------------------------------------------------------------------------

describe('ActionBar — Stop button', () => {
  it('calls onOpenCancel when Stop is clicked during generation', async () => {
    const onOpenCancel = vi.fn();
    renderBar(makeEpisode({ status: 'generating' }), { onOpenCancel });
    await userEvent.click(screen.getByRole('button', { name: /stop/i }));
    expect(onOpenCancel).toHaveBeenCalledTimes(1);
  });
});

// ---------------------------------------------------------------------------
// 4. Overflow menu — delete
// ---------------------------------------------------------------------------

describe('ActionBar — overflow menu', () => {
  it('calls onOpenDelete when Delete is activated from the overflow menu', async () => {
    const onOpenDelete = vi.fn();
    renderBar(makeEpisode({ status: 'draft' }), { onOpenDelete });

    // Open the overflow menu (aria-label: "More actions")
    await userEvent.click(
      screen.getByRole('button', { name: /more actions/i }),
    );

    // Delete should now be visible
    const deleteBtn = await screen.findByRole('button', { name: /delete/i });
    await userEvent.click(deleteBtn);

    expect(onOpenDelete).toHaveBeenCalledTimes(1);
  });

  it('shows Reset to draft in overflow menu for non-draft statuses', async () => {
    renderBar(makeEpisode({ status: 'review' }));

    await userEvent.click(
      screen.getByRole('button', { name: /more actions/i }),
    );

    expect(
      await screen.findByRole('button', { name: /reset to draft/i }),
    ).toBeInTheDocument();
  });

  it('does NOT show Reset to draft in overflow menu when status is draft', async () => {
    renderBar(makeEpisode({ status: 'draft' }));

    await userEvent.click(
      screen.getByRole('button', { name: /more actions/i }),
    );

    // Wait for menu to open
    await screen.findByRole('button', { name: /delete/i });

    expect(
      screen.queryByRole('button', { name: /reset to draft/i }),
    ).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// 5. Status pill text
// ---------------------------------------------------------------------------

describe('ActionBar — status pill', () => {
  const statuses = [
    'draft',
    'generating',
    'review',
    'editing',
    'exported',
    'failed',
  ] as const;

  for (const s of statuses) {
    it(`renders status pill with text "${s}"`, () => {
      renderBar(makeEpisode({ status: s }));
      // Badge text is the status value itself
      expect(screen.getByText(s)).toBeInTheDocument();
    });
  }
});

// ---------------------------------------------------------------------------
// 6. Title rendered in the banner
// ---------------------------------------------------------------------------

describe('ActionBar — title', () => {
  it('renders the episode title in the banner', () => {
    renderBar(makeEpisode({ title: 'My Great Episode' }));
    expect(screen.getByText('My Great Episode')).toBeInTheDocument();
  });
});
