/**
 * ActivityMonitor behaviour tests.
 *
 * Two canonical cases required by the spec:
 *   1. BulkActions strip is hidden when jobs.length === 0 and failedCount === 0.
 *   2. Worker pill announces status changes (aria-live="polite" on worker label).
 *
 * We test the sub-components directly to keep the mocking surface small.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { ReactNode } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

import { TooltipProvider } from '@/components/ui/Tooltip';
import { BulkActions } from './BulkActions';
import { HeaderStrip } from './HeaderStrip';

// ---------------------------------------------------------------------------
// Wrapper — Radix Tooltip requires TooltipProvider in the tree
// ---------------------------------------------------------------------------

function Wrapper({ children }: { children: ReactNode }) {
  return (
    <MemoryRouter>
      <TooltipProvider delayDuration={0}>{children}</TooltipProvider>
    </MemoryRouter>
  );
}

// ---------------------------------------------------------------------------
// BulkActions
// ---------------------------------------------------------------------------

describe('BulkActions', () => {
  const noop = vi.fn();

  beforeEach(() => {
    noop.mockClear();
  });

  it('renders nothing when totalActive === 0 and failedCount === 0', () => {
    render(
      <Wrapper>
        <BulkActions
          totalActive={0}
          failedCount={0}
          onPauseAll={noop}
          onCancelAll={noop}
          onRetryFailed={noop}
          onCleanup={noop}
        />
      </Wrapper>,
    );
    // BulkActions returns null, so the strip is absent.
    expect(screen.queryByTestId('bulk-actions-strip')).toBeNull();
  });

  it('renders when totalActive > 0', () => {
    render(
      <Wrapper>
        <BulkActions
          totalActive={2}
          failedCount={0}
          onPauseAll={noop}
          onCancelAll={noop}
          onRetryFailed={noop}
          onCleanup={noop}
        />
      </Wrapper>,
    );
    expect(screen.getByTestId('bulk-actions-strip')).toBeInTheDocument();
  });

  it('renders when failedCount > 0 (even with no active jobs)', () => {
    render(
      <Wrapper>
        <BulkActions
          totalActive={0}
          failedCount={3}
          onPauseAll={noop}
          onCancelAll={noop}
          onRetryFailed={noop}
          onCleanup={noop}
        />
      </Wrapper>,
    );
    expect(screen.getByTestId('bulk-actions-strip')).toBeInTheDocument();
  });

  it('shows Retry button only when failedCount > 0', () => {
    const { rerender } = render(
      <Wrapper>
        <BulkActions
          totalActive={1}
          failedCount={0}
          onPauseAll={noop}
          onCancelAll={noop}
          onRetryFailed={noop}
          onCleanup={noop}
        />
      </Wrapper>,
    );
    expect(screen.queryByRole('button', { name: /retry/i })).toBeNull();

    rerender(
      <Wrapper>
        <BulkActions
          totalActive={1}
          failedCount={2}
          onPauseAll={noop}
          onCancelAll={noop}
          onRetryFailed={noop}
          onCleanup={noop}
        />
      </Wrapper>,
    );
    expect(screen.getByRole('button', { name: /retry 2 failed/i })).toBeInTheDocument();
  });

  it('calls onPauseAll when Pause button is clicked', async () => {
    render(
      <Wrapper>
        <BulkActions
          totalActive={1}
          failedCount={0}
          onPauseAll={noop}
          onCancelAll={vi.fn()}
          onRetryFailed={vi.fn()}
          onCleanup={vi.fn()}
        />
      </Wrapper>,
    );
    await userEvent.click(screen.getByRole('button', { name: /pause all/i }));
    expect(noop).toHaveBeenCalledOnce();
  });

  it('calls onCancelAll when Cancel button is clicked', async () => {
    const onCancelAll = vi.fn();
    render(
      <Wrapper>
        <BulkActions
          totalActive={1}
          failedCount={0}
          onPauseAll={vi.fn()}
          onCancelAll={onCancelAll}
          onRetryFailed={vi.fn()}
          onCleanup={vi.fn()}
        />
      </Wrapper>,
    );
    await userEvent.click(screen.getByRole('button', { name: /cancel all/i }));
    expect(onCancelAll).toHaveBeenCalledOnce();
  });

  it('hides Cancel button when totalActive === 0 (only failedCount triggers strip)', () => {
    render(
      <Wrapper>
        <BulkActions
          totalActive={0}
          failedCount={1}
          onPauseAll={noop}
          onCancelAll={noop}
          onRetryFailed={noop}
          onCleanup={noop}
        />
      </Wrapper>,
    );
    // Strip is visible because failedCount > 0
    expect(screen.getByTestId('bulk-actions-strip')).toBeInTheDocument();
    // But Cancel is hidden because totalActive === 0
    expect(screen.queryByRole('button', { name: /cancel all/i })).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// HeaderStrip — aria-live worker announcement
// ---------------------------------------------------------------------------

describe('HeaderStrip — worker status aria-live', () => {
  const baseProps = {
    wsConnected: true,
    queueStatus: { active: 1, queued: 0, max_concurrent: 4 },
    priority: 'shorts_first' as const,
    restartingWorker: false,
    onRestartWorker: vi.fn(),
    onPriorityChange: vi.fn(),
    expanded: false,
    onToggleExpanded: vi.fn(),
  };

  it('renders the worker status element with role=status and aria-live=polite', () => {
    render(
      <Wrapper>
        <HeaderStrip workerHealth={{ alive: true }} {...baseProps} />
      </Wrapper>,
    );
    const status = screen.getByRole('status');
    expect(status).toBeInTheDocument();
    expect(status).toHaveAttribute('aria-live', 'polite');
  });

  it('displays "Worker: Active" when workerHealth.alive is true', () => {
    render(
      <Wrapper>
        <HeaderStrip workerHealth={{ alive: true }} {...baseProps} />
      </Wrapper>,
    );
    expect(screen.getByRole('status')).toHaveTextContent(/worker.*active/i);
  });

  it('displays "Worker: Down" when workerHealth.alive is false', () => {
    render(
      <Wrapper>
        <HeaderStrip workerHealth={{ alive: false }} {...baseProps} />
      </Wrapper>,
    );
    expect(screen.getByRole('status')).toHaveTextContent(/worker.*down/i);
  });

  it('displays "Worker: Unknown" when workerHealth is null (loading)', () => {
    render(
      <Wrapper>
        <HeaderStrip workerHealth={null} {...baseProps} />
      </Wrapper>,
    );
    expect(screen.getByRole('status')).toHaveTextContent(/worker.*unknown/i);
  });

  it('shows the Restart button only when worker is down', () => {
    const { rerender } = render(
      <Wrapper>
        <HeaderStrip workerHealth={{ alive: true }} {...baseProps} />
      </Wrapper>,
    );
    expect(screen.queryByRole('button', { name: /restart worker/i })).toBeNull();

    rerender(
      <Wrapper>
        <HeaderStrip workerHealth={{ alive: false }} {...baseProps} />
      </Wrapper>,
    );
    expect(screen.getByRole('button', { name: /restart worker/i })).toBeInTheDocument();
  });

  it('calls onRestartWorker when Restart is clicked', async () => {
    const onRestartWorker = vi.fn();
    render(
      <Wrapper>
        <HeaderStrip
          workerHealth={{ alive: false }}
          {...baseProps}
          onRestartWorker={onRestartWorker}
        />
      </Wrapper>,
    );
    await userEvent.click(screen.getByRole('button', { name: /restart worker/i }));
    expect(onRestartWorker).toHaveBeenCalledOnce();
  });

  it('calls onPriorityChange when the priority select changes', async () => {
    const onPriorityChange = vi.fn();
    render(
      <Wrapper>
        <HeaderStrip
          workerHealth={{ alive: true }}
          {...baseProps}
          onPriorityChange={onPriorityChange}
        />
      </Wrapper>,
    );
    const select = screen.getByRole('combobox', { name: /queue priority/i });
    await userEvent.selectOptions(select, 'longform_first');
    expect(onPriorityChange).toHaveBeenCalledWith('longform_first');
  });
});
