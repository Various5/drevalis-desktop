import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Channels from './Channels';

// YouTube + TikTok connected; the rest disconnected.
vi.mock('@/lib/useConnectedPlatforms', () => ({
  useConnectedPlatforms: () => ({
    socials: ['tiktok'],
    youtubeConnected: true,
    ready: true,
    refresh: vi.fn(),
  }),
}));

describe('Channels hub', () => {
  it('shows a card for every supported platform', () => {
    render(
      <MemoryRouter>
        <Channels />
      </MemoryRouter>,
    );
    for (const label of ['YouTube', 'TikTok', 'Instagram', 'Facebook', 'X']) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it('shows Manage for connected platforms and Connect for the rest', () => {
    render(
      <MemoryRouter>
        <Channels />
      </MemoryRouter>,
    );
    // youtube + tiktok → Manage (2); instagram + facebook + x → Connect (3)
    expect(screen.getAllByRole('button', { name: /^manage/i })).toHaveLength(2);
    expect(screen.getAllByRole('button', { name: /^connect/i })).toHaveLength(3);
  });
});
