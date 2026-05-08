import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import type { UseQueryResult } from '@tanstack/react-query';
import type { EpisodeListItem, GenerationJobListItem, SeriesListItem } from '@/types';
import type { DashboardLayout } from './types';

// =============================================================================
// Mock declarations — hoisted so vitest can hoist them before module init.
// =============================================================================

// ── usePreferences ────────────────────────────────────────────────────────
let mockPrefs: DashboardLayout | undefined;
const mockUpdatePrefs = vi.fn();

vi.mock('@/lib/usePreferences', () => ({
  usePreferences: () => ({
    prefs: mockPrefs,
    update: mockUpdatePrefs,
    isLoading: false,
  }),
}));

// ── useActiveJobsProgress ─────────────────────────────────────────────────
let mockLatestByEpisode: Record<string, Record<string, unknown>> = {};

vi.mock('@/lib/websocket', () => ({
  useActiveJobsProgress: () => ({
    connected: false,
    latestByEpisode: mockLatestByEpisode,
  }),
}));

// ── data query hooks ──────────────────────────────────────────────────────
let mockRecentEpisodes: EpisodeListItem[] = [];
let mockAllEpisodes: EpisodeListItem[] = [];
let mockSeriesList: SeriesListItem[] = [];
let mockActiveJobs: GenerationJobListItem[] = [];

vi.mock('@/lib/queries', () => ({
  useRecentEpisodes: (): Partial<UseQueryResult<EpisodeListItem[]>> => ({
    data: mockRecentEpisodes,
    isPending: false,
    error: null,
  }),
  useEpisodes: (): Partial<UseQueryResult<EpisodeListItem[]>> => ({
    data: mockAllEpisodes,
    isPending: false,
    error: null,
  }),
  useSeries: (): Partial<UseQueryResult<SeriesListItem[]>> => ({
    data: mockSeriesList,
    isPending: false,
    error: null,
  }),
  useActiveJobs: (): Partial<UseQueryResult<GenerationJobListItem[]>> => ({
    data: mockActiveJobs,
    isPending: false,
    error: null,
  }),
  useSystemHealth: () => ({ data: undefined }),
}));

// ── navigation ────────────────────────────────────────────────────────────
const navigateSpy = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>(
    'react-router-dom',
  );
  return {
    ...actual,
    useNavigate: () => navigateSpy,
  };
});

// ── SetupChecklist / SystemHealthCard — render nothing in unit tests ──────
vi.mock('@/components/SetupChecklist', () => ({
  SetupChecklist: () => null,
}));
vi.mock('@/components/SystemHealthCard', () => ({
  SystemHealthCard: () => null,
}));

// ── Toast ─────────────────────────────────────────────────────────────────
vi.mock('@/components/ui/Toast', () => ({
  useToast: () => ({ toast: { error: vi.fn() } }),
}));

// =============================================================================
// Helpers
// =============================================================================

import Dashboard from './index';

function renderDashboard() {
  return render(
    <MemoryRouter>
      <Dashboard />
    </MemoryRouter>,
  );
}

// =============================================================================
// Tests
// =============================================================================

beforeEach(() => {
  mockPrefs = undefined;
  mockLatestByEpisode = {};
  mockRecentEpisodes = [];
  mockAllEpisodes = [];
  mockSeriesList = [];
  mockActiveJobs = [];
  mockUpdatePrefs.mockClear();
  navigateSpy.mockClear();
});

// ---------------------------------------------------------------------------
// 1. Default layout: all default widgets present
// ---------------------------------------------------------------------------

describe('Dashboard — default layout', () => {
  it('renders all default visible widgets when no prefs are stored', () => {
    mockPrefs = undefined; // fall back to DEFAULT_LAYOUT
    renderDashboard();

    // stat-cards: the 4 stat labels (rendered mixed-case; CSS uppercase is visual only)
    expect(screen.getByText('Total Episodes')).toBeInTheDocument();
    expect(screen.getByText('Completed')).toBeInTheDocument();
    expect(screen.getByText('Failed')).toBeInTheDocument();
    expect(screen.getByText('Total Series')).toBeInTheDocument();

    // quick-actions
    expect(screen.getByRole('button', { name: /create new series/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /view content calendar/i })).toBeInTheDocument();

    // activity-timeline heading
    expect(screen.getByText('Recent Activity')).toBeInTheDocument();

    // recent-episodes heading
    expect(screen.getByRole('heading', { name: /recent episodes/i })).toBeInTheDocument();
  });

  it('does NOT render active-jobs panel when no active jobs', () => {
    mockPrefs = undefined;
    mockActiveJobs = [];
    renderDashboard();
    // "Active Jobs" heading only appears when there are jobs
    expect(screen.queryByText(/active jobs \(/i)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// 2. Hidden widget not rendered
// ---------------------------------------------------------------------------

describe('Dashboard — hidden widget', () => {
  it('does not render recent-episodes when it is in the hidden list', () => {
    mockPrefs = {
      version: 1,
      widgets: ['stat-cards', 'quick-actions', 'activity-timeline'],
      hidden: ['setup-checklist', 'system-health', 'recent-episodes', 'active-jobs'],
    };
    renderDashboard();

    // activity-timeline is visible
    expect(screen.getByText('Recent Activity')).toBeInTheDocument();

    // recent-episodes heading should NOT be present
    expect(screen.queryByRole('heading', { name: /recent episodes/i })).toBeNull();
  });

  it('renders a single widget when only one widget is in the visible list', () => {
    mockPrefs = {
      version: 1,
      widgets: ['stat-cards'],
      hidden: ['setup-checklist', 'system-health', 'quick-actions', 'recent-episodes', 'activity-timeline', 'active-jobs'],
    };
    renderDashboard();

    expect(screen.getByText('Total Episodes')).toBeInTheDocument();
    expect(screen.queryByText('Recent Activity')).toBeNull();
    expect(screen.queryByRole('heading', { name: /recent episodes/i })).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// 3. Edit mode: drag handle + hide button visible / invisible
// ---------------------------------------------------------------------------

describe('Dashboard — edit mode', () => {
  it('does not show drag handles or hide buttons outside edit mode', () => {
    mockPrefs = {
      version: 1,
      widgets: ['stat-cards'],
      hidden: ['setup-checklist', 'system-health', 'quick-actions', 'recent-episodes', 'activity-timeline', 'active-jobs'],
    };
    renderDashboard();
    expect(screen.queryByRole('button', { name: /drag to reorder/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /hide widget/i })).toBeNull();
  });

  it('shows drag handles and hide buttons in edit mode after clicking Customize', async () => {
    mockPrefs = {
      version: 1,
      widgets: ['stat-cards', 'quick-actions'],
      hidden: ['setup-checklist', 'system-health', 'recent-episodes', 'activity-timeline', 'active-jobs'],
    };

    // Simulate desktop (innerWidth >= 768) so Customize enters inline edit
    // mode instead of opening the mobile dialog.
    const originalInnerWidth = Object.getOwnPropertyDescriptor(window, 'innerWidth');
    Object.defineProperty(window, 'innerWidth', { value: 1024, writable: true, configurable: true });

    renderDashboard();

    const customizeBtn = screen.getByRole('button', { name: /customize dashboard/i });
    await userEvent.click(customizeBtn);

    // Drag handles (hidden below md via CSS but present in DOM)
    const dragHandles = screen.getAllByRole('button', { name: /drag to reorder/i });
    expect(dragHandles.length).toBeGreaterThan(0);

    // Hide buttons
    const hideButtons = screen.getAllByRole('button', { name: /hide widget/i });
    expect(hideButtons.length).toBeGreaterThan(0);

    // Restore
    if (originalInnerWidth) {
      Object.defineProperty(window, 'innerWidth', originalInnerWidth);
    }
  });

  it('hides drag handles and hide buttons after clicking Done', async () => {
    mockPrefs = {
      version: 1,
      widgets: ['stat-cards'],
      hidden: ['setup-checklist', 'system-health', 'quick-actions', 'recent-episodes', 'activity-timeline', 'active-jobs'],
    };

    Object.defineProperty(window, 'innerWidth', { value: 1024, writable: true, configurable: true });

    renderDashboard();

    // Enter edit mode
    await userEvent.click(screen.getByRole('button', { name: /customize dashboard/i }));

    // Confirm edit mode is active (Done button present)
    const doneBtn = screen.getByRole('button', { name: /exit customize mode/i });
    expect(doneBtn).toBeInTheDocument();

    // Drag handles present
    expect(screen.getAllByRole('button', { name: /drag to reorder/i }).length).toBeGreaterThan(0);

    // Exit edit mode
    await userEvent.click(doneBtn);

    // Drag handles gone
    expect(screen.queryByRole('button', { name: /drag to reorder/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /hide widget/i })).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// 4. Hide a widget from edit mode
// ---------------------------------------------------------------------------

describe('Dashboard — hide widget interaction', () => {
  it('calls update with the widget moved to hidden when the hide button is clicked', async () => {
    mockPrefs = {
      version: 1,
      widgets: ['stat-cards', 'quick-actions'],
      hidden: ['setup-checklist', 'system-health', 'recent-episodes', 'activity-timeline', 'active-jobs'],
    };

    Object.defineProperty(window, 'innerWidth', { value: 1024, writable: true, configurable: true });

    renderDashboard();

    await userEvent.click(screen.getByRole('button', { name: /customize dashboard/i }));

    // Click hide on stat-cards
    const hideStatCards = screen.getByRole('button', { name: /hide widget: stat-cards/i });
    await userEvent.click(hideStatCards);

    // update should have been called with stat-cards removed from widgets
    expect(mockUpdatePrefs).toHaveBeenCalledTimes(1);
    const call = mockUpdatePrefs.mock.calls[0];
    expect(call).toBeDefined();
    const arg = call![0] as DashboardLayout;
    expect(arg.widgets).not.toContain('stat-cards');
    expect(arg.hidden).toContain('stat-cards');
  });
});

// ---------------------------------------------------------------------------
// 5. Active-jobs widget auto-shows when there are active jobs
// ---------------------------------------------------------------------------

describe('Dashboard — active-jobs auto-show', () => {
  it('renders active-jobs panel even when it is in hidden prefs, if there are active jobs', () => {
    mockPrefs = {
      version: 1,
      widgets: ['stat-cards'],
      hidden: ['setup-checklist', 'system-health', 'quick-actions', 'recent-episodes', 'activity-timeline', 'active-jobs'],
    };
    mockActiveJobs = [
      {
        id: 'job-1',
        episode_id: 'ep-1',
        step: 'script',
        status: 'running',
        progress_pct: 50,
        error_message: null,
        retry_count: 0,
        created_at: new Date().toISOString(),
      },
    ];
    renderDashboard();

    // Active Jobs heading appears even though 'active-jobs' was hidden
    expect(screen.getByText(/active jobs \(1\)/i)).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// 6. Invalid / mismatched prefs version falls back to DEFAULT_LAYOUT
// ---------------------------------------------------------------------------

describe('Dashboard — prefs schema validation', () => {
  it('falls back to DEFAULT_LAYOUT when version is wrong', () => {
    // Simulate a future-bumped prefs that this version doesn't understand.
    mockPrefs = { version: 99 } as unknown as DashboardLayout;
    renderDashboard();

    // Default layout includes stat-cards
    expect(screen.getByText('Total Episodes')).toBeInTheDocument();
    // Default layout includes activity-timeline
    expect(screen.getByText('Recent Activity')).toBeInTheDocument();
  });
});
