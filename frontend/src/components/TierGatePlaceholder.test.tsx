import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { TierGatePlaceholder, isTierGateError } from './TierGatePlaceholder';
import { ApiError } from '@/lib/api';

// ---------------------------------------------------------------------------
// Test fixtures
// ---------------------------------------------------------------------------

const renderWithRouter = (ui: React.ReactElement) =>
  render(<MemoryRouter>{ui}</MemoryRouter>);

const tierError = (overrides: Record<string, unknown> = {}): ApiError =>
  new ApiError(402, 'Payment Required', undefined, {
    error: 'feature_not_in_tier',
    feature: 'audiobooks',
    tier: 'pro',
    current_tier: 'creator',
    ...overrides,
  });

// ---------------------------------------------------------------------------
// isTierGateError
// ---------------------------------------------------------------------------

describe('isTierGateError', () => {
  it('returns true for a 402 ApiError carrying feature detail', () => {
    expect(isTierGateError(tierError())).toBe(true);
  });

  it('returns false for a non-402 ApiError', () => {
    expect(isTierGateError(new ApiError(500, 'Internal', undefined, {}))).toBe(false);
  });

  it('returns false for a 402 ApiError without feature detail', () => {
    expect(
      isTierGateError(new ApiError(402, 'Payment Required', undefined, {})),
    ).toBe(false);
  });

  it('returns false for non-ApiError values', () => {
    expect(isTierGateError(new Error('boom'))).toBe(false);
    expect(isTierGateError(null)).toBe(false);
    expect(isTierGateError(undefined)).toBe(false);
    expect(isTierGateError('not a license error')).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// TierGatePlaceholder rendering
// ---------------------------------------------------------------------------

describe('TierGatePlaceholder', () => {
  it('renders nothing for a non-402 error', () => {
    const { container } = renderWithRouter(
      <TierGatePlaceholder error={new ApiError(500, 'Internal', undefined, {})} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders nothing when error is not an ApiError', () => {
    const { container } = renderWithRouter(
      <TierGatePlaceholder error={new Error('something else')} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders feature label, tier, and current tier from detailRaw', () => {
    renderWithRouter(<TierGatePlaceholder error={tierError()} />);
    // The feature name is shown as the heading (with underscores replaced)
    expect(screen.getByText(/audiobooks/i)).toBeInTheDocument();
    // The tier and current tier appear together in a sentence describing
    // the upgrade path
    expect(screen.getByText(/pro/i)).toBeInTheDocument();
    expect(screen.getByText(/creator/i)).toBeInTheDocument();
  });

  it('replaces underscores in the feature name with spaces', () => {
    const err = tierError({ feature: 'cross_platform_bulk' });
    renderWithRouter(<TierGatePlaceholder error={err} />);
    // "cross_platform_bulk" → "cross platform bulk"
    expect(screen.getByText(/cross platform bulk/i)).toBeInTheDocument();
  });

  it('uses featureLabel override when given, ignoring detailRaw.feature', () => {
    renderWithRouter(
      <TierGatePlaceholder error={tierError()} featureLabel="Text to Voice" />,
    );
    expect(screen.getByText(/text to voice/i)).toBeInTheDocument();
    // The raw feature name should not appear
    expect(screen.queryByRole('heading', { name: /audiobooks/i })).toBeNull();
  });

  it('exposes an Upgrade button that triggers the override callback', async () => {
    const onUpgrade = vi.fn();
    renderWithRouter(
      <TierGatePlaceholder error={tierError()} onUpgrade={onUpgrade} />,
    );
    await userEvent.click(screen.getByRole('button', { name: /upgrade/i }));
    expect(onUpgrade).toHaveBeenCalledOnce();
  });

  it('falls back to friendly defaults when tier / current_tier are missing', () => {
    const err = new ApiError(402, 'Payment Required', undefined, {
      error: 'feature_not_in_tier',
      feature: 'audiobooks',
      // tier + current_tier deliberately omitted
    });
    renderWithRouter(<TierGatePlaceholder error={err} />);
    // The component should render rather than crash
    expect(screen.getByText(/audiobooks/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /upgrade/i })).toBeInTheDocument();
  });
});
