import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import i18n from '@/lib/i18n';
import { axe } from '@/test/axe';
import { CommandPalette } from './CommandPalette';

// No dynamic series / recent episode → only the static routes + actions render.
vi.mock('@/lib/queries', () => ({
  useSeries: () => ({ data: [] }),
  useRecentEpisodes: () => ({ data: [] }),
}));

afterEach(async () => {
  // Restore the default language so we don't leak de-DE into later tests.
  await i18n.changeLanguage('en-US');
});

function renderPalette() {
  return render(
    <MemoryRouter>
      <CommandPalette open onClose={() => {}} />
    </MemoryRouter>,
  );
}

describe('CommandPalette — i18n', () => {
  it('renders English chrome, route labels (reused nav keys), and action labels', () => {
    renderPalette();
    expect(screen.getByPlaceholderText('Jump to a page or action…')).toBeInTheDocument();
    expect(screen.getByText('Dashboard')).toBeInTheDocument();
    expect(screen.getByText('Home overview')).toBeInTheDocument();
    expect(screen.getByText('New Episode')).toBeInTheDocument();
  });

  it('renders German strings after a language switch', async () => {
    await i18n.changeLanguage('de-DE');
    renderPalette();
    expect(
      screen.getByPlaceholderText('Zu einer Seite oder Aktion springen…'),
    ).toBeInTheDocument();
    expect(screen.getByText('Serien verwalten')).toBeInTheDocument(); // Series hint
    expect(screen.getByText('Neue Episode')).toBeInTheDocument();
    expect(screen.getByText('YouTube verbinden')).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { container } = renderPalette();
    expect(await axe(container)).toHaveNoViolations();
  });
});
