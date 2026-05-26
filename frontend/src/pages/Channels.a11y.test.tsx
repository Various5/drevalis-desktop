/**
 * Accessibility audit for the Channels hub (Phase 5 a11y) — a representative
 * content page: a grid of platform cards mixing connected ("Manage") and
 * disconnected ("Connect") states, each with status text and actions. Asserts
 * zero axe violations across that mix.
 */
import { describe, it, expect, vi } from 'vitest';
import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { axe } from '@/test/axe';
import Channels from './Channels';

vi.mock('@/lib/useConnectedPlatforms', () => ({
  useConnectedPlatforms: () => ({
    socials: ['tiktok'],
    youtubeConnected: true,
    ready: true,
    refresh: vi.fn(),
  }),
}));

describe('Channels hub — a11y', () => {
  it('has no axe violations with connected + disconnected platforms', async () => {
    const { container } = render(
      <MemoryRouter>
        <Channels />
      </MemoryRouter>,
    );
    expect(await axe(container)).toHaveNoViolations();
  });
});
