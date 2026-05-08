import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { SystemHealthCard } from './SystemHealthCard';
import type { HealthCheck } from '@/types';
import type { UseQueryResult } from '@tanstack/react-query';

// ---------------------------------------------------------------------------
// Hook mock + navigate spy
// ---------------------------------------------------------------------------

// Captures whatever ``useSystemHealth`` should return for each test. The
// component only reads ``q.data`` so we don't need a full UseQueryResult
// surface — just a thin partial.
let mockHealthData: HealthCheck | undefined;

vi.mock('@/lib/queries', () => ({
  useSystemHealth: (): Partial<UseQueryResult<HealthCheck>> => ({
    data: mockHealthData,
  }),
}));

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

// ---------------------------------------------------------------------------
// Test scaffolding
// ---------------------------------------------------------------------------

const renderCard = () =>
  render(
    <MemoryRouter>
      <SystemHealthCard />
    </MemoryRouter>,
  );

beforeEach(() => {
  mockHealthData = undefined;
  navigateSpy.mockClear();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('SystemHealthCard', () => {
  it('renders nothing while data is loading', () => {
    mockHealthData = undefined;
    const { container } = renderCard();
    expect(container.firstChild).toBeNull();
  });

  it('renders nothing when overall health is ok', () => {
    mockHealthData = { overall: 'ok', services: [] };
    const { container } = renderCard();
    expect(container.firstChild).toBeNull();
  });

  it('renders nothing when the services list has no problems', () => {
    // Edge case: overall came back degraded but every individual
    // service is 'ok' (data race during a refresh). The component
    // gates on the filtered problems list, not just ``overall``.
    mockHealthData = {
      overall: 'degraded',
      services: [{ name: 'comfyui', status: 'ok', message: '' }],
    };
    const { container } = renderCard();
    expect(container.firstChild).toBeNull();
  });

  it('renders the unhealthy state header when overall is unhealthy', () => {
    mockHealthData = {
      overall: 'unhealthy',
      services: [
        { name: 'comfyui', status: 'unreachable', message: 'connection refused' },
      ],
    };
    renderCard();
    expect(screen.getByRole('heading', { level: 3, name: /unhealthy/i })).toBeInTheDocument();
  });

  it('renders the degraded state header when overall is degraded', () => {
    mockHealthData = {
      overall: 'degraded',
      services: [
        { name: 'llm', status: 'degraded', message: 'slow response' },
      ],
    };
    renderCard();
    expect(screen.getByRole('heading', { level: 3, name: /degraded/i })).toBeInTheDocument();
  });

  it('lists each problem service with name + message', () => {
    mockHealthData = {
      overall: 'degraded',
      services: [
        { name: 'comfyui', status: 'unreachable', message: 'connection refused' },
        { name: 'llm', status: 'degraded', message: 'slow response' },
        { name: 'ffmpeg', status: 'ok', message: '' },
      ],
    };
    renderCard();
    // Two problem services rendered; the healthy one is filtered out.
    expect(screen.getByText('comfyui')).toBeInTheDocument();
    expect(screen.getByText(/connection refused/)).toBeInTheDocument();
    expect(screen.getByText('llm')).toBeInTheDocument();
    expect(screen.getByText(/slow response/)).toBeInTheDocument();
    expect(screen.queryByText('ffmpeg')).toBeNull();
  });

  it('falls back to status when a problem has no message', () => {
    mockHealthData = {
      overall: 'degraded',
      services: [{ name: 'storage', status: 'unreachable', message: '' }],
    };
    renderCard();
    // No human message → status text is shown
    expect(screen.getByText('unreachable')).toBeInTheDocument();
  });

  it('Investigate button navigates to settings → health', async () => {
    mockHealthData = {
      overall: 'degraded',
      services: [{ name: 'llm', status: 'degraded', message: 'timeout' }],
    };
    renderCard();
    await userEvent.click(screen.getByRole('button', { name: /investigate/i }));
    expect(navigateSpy).toHaveBeenCalledWith('/settings?section=health');
  });
});
