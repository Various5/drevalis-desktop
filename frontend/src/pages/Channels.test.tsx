import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import i18n from '@/lib/i18n';
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

afterEach(async () => {
  await i18n.changeLanguage('en-US');
});

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

  it('renders German copy after a language switch', async () => {
    await i18n.changeLanguage('de-DE');
    render(
      <MemoryRouter>
        <Channels />
      </MemoryRouter>,
    );
    expect(screen.getByText(/^Verbinde die Plattformen/)).toBeInTheDocument(); // intro
    expect(screen.getAllByText('Verwalten')).toHaveLength(2); // connected
    expect(screen.getAllByText('Verbinden')).toHaveLength(3); // disconnected
    // Platform names stay proper nouns.
    expect(screen.getByText('YouTube')).toBeInTheDocument();
  });
});
