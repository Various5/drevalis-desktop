import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ToastProvider } from '@/components/ui/Toast';
import CharacterPacks from './_monolith';
import { ApiError } from '@/lib/api';
import type { CharacterPack } from '@/types';

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock('@/lib/api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('@/lib/api')>();
  return {
    ...mod,
    characterPacks: {
      list: vi.fn(),
      create: vi.fn(),
      delete: vi.fn(),
      apply: vi.fn(),
    },
  };
});

// AssetLockPicker uses AssetPicker which calls the assets API and opens a
// Dialog. Stub it out so tests don't need a full asset-list fixture.
vi.mock('@/pages/SeriesDetail/sections/AssetLockPicker', () => ({
  AssetLockPicker: ({ title }: { title: string }) => (
    <div data-testid="asset-lock-picker">{title}</div>
  ),
}));

// useSeries is used inside ApplyDialog — stub with empty data so the
// dialog can be rendered without a QueryClient provider.
vi.mock('@/lib/queries', () => ({
  useSeries: () => ({ data: [], isLoading: false }),
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makePack(overrides: Partial<CharacterPack> = {}): CharacterPack {
  return {
    id: 'pack-1',
    name: 'Test Pack',
    description: 'A test pack',
    thumbnail_asset_id: null,
    character_lock: null,
    style_lock: null,
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

function tierGateError(): ApiError {
  return new ApiError(402, 'Payment Required', undefined, {
    error: 'feature_not_in_tier',
    feature: 'character_packs',
    tier: 'pro',
    current_tier: 'creator',
  });
}

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter>
          <CharacterPacks />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

// ---------------------------------------------------------------------------
// Reset
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// 1. Empty state
// ---------------------------------------------------------------------------

describe('CharacterPacks — empty state', () => {
  it('renders the empty state when the list returns []', async () => {
    const { characterPacks } = await import('@/lib/api');
    vi.mocked(characterPacks.list).mockResolvedValue([]);

    renderPage();

    await waitFor(() => {
      expect(screen.getByText(/no saved packs/i)).toBeInTheDocument();
    });
  });

  it('renders a "New Pack" CTA in the empty state', async () => {
    const { characterPacks } = await import('@/lib/api');
    vi.mocked(characterPacks.list).mockResolvedValue([]);

    renderPage();

    await waitFor(() => {
      const btns = screen.getAllByRole('button', { name: /new pack/i });
      expect(btns.length).toBeGreaterThan(0);
    });
  });
});

// ---------------------------------------------------------------------------
// 2. Tier gate
// ---------------------------------------------------------------------------

describe('CharacterPacks — tier gate', () => {
  it('renders TierGatePlaceholder when the list returns 402', async () => {
    const { characterPacks } = await import('@/lib/api');
    vi.mocked(characterPacks.list).mockRejectedValue(tierGateError());

    renderPage();

    await waitFor(() => {
      // The TierGatePlaceholder renders the feature label or the raw name
      expect(screen.getByText(/character packs/i)).toBeInTheDocument();
    });
  });

  it('shows the Upgrade button for tier gate errors', async () => {
    const { characterPacks } = await import('@/lib/api');
    vi.mocked(characterPacks.list).mockRejectedValue(tierGateError());

    renderPage();

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /upgrade/i })).toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// 3. Card grid with data
// ---------------------------------------------------------------------------

describe('CharacterPacks — card grid', () => {
  it('renders a card for each pack returned by the list', async () => {
    const { characterPacks } = await import('@/lib/api');
    const packs = [
      makePack({ id: 'p1', name: 'Hero Pack' }),
      makePack({ id: 'p2', name: 'Villain Pack', description: 'Dark vibes' }),
    ];
    vi.mocked(characterPacks.list).mockResolvedValue(packs);

    renderPage();

    await waitFor(() => {
      expect(screen.getByText('Hero Pack')).toBeInTheDocument();
      expect(screen.getByText('Villain Pack')).toBeInTheDocument();
    });
  });

  it('renders an "Apply to series" button for each pack', async () => {
    const { characterPacks } = await import('@/lib/api');
    vi.mocked(characterPacks.list).mockResolvedValue([
      makePack({ id: 'p1', name: 'Alpha Pack' }),
      makePack({ id: 'p2', name: 'Beta Pack' }),
    ]);

    renderPage();

    await waitFor(() => {
      const applyBtns = screen.getAllByRole('button', {
        name: /apply to series/i,
      });
      expect(applyBtns).toHaveLength(2);
    });
  });

  it('shows "Character lock" tag when character_lock is set', async () => {
    const { characterPacks } = await import('@/lib/api');
    vi.mocked(characterPacks.list).mockResolvedValue([
      makePack({ id: 'p1', name: 'Locked Pack', character_lock: { asset_ids: 'abc', strength: 0.8 } }),
    ]);

    renderPage();

    await waitFor(() => {
      expect(screen.getByText(/character lock/i)).toBeInTheDocument();
    });
  });
});
