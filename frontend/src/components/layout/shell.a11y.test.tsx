/**
 * Accessibility audit for the app-shell navigation (Phase 5 a11y).
 *
 * Sidebar + MobileNav frame every screen, so an a11y regression here is felt
 * everywhere. These render the components in their distinct states — including
 * the collapsed icon-only sidebar (links must keep an accessible name via
 * ``title``) and the open mobile group sheet (menu / menuitem roles) — and
 * assert zero axe violations. A non-zero generating count exercises the
 * job-badge / status-dot ``aria-label`` paths.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { axe } from '@/test/axe';
import { Sidebar } from './Sidebar';
import { MobileNav } from './MobileNav';

vi.mock('@/lib/queries', () => ({
  useJobsStatus: () => ({ data: { generating_episodes: 3 } }),
}));
vi.mock('@/lib/websocket', () => ({
  useActiveJobsProgress: () => ({ latestByEpisode: { ep1: {}, ep2: {} } }),
}));

describe('app shell navigation — a11y', () => {
  it('Sidebar (expanded)', async () => {
    const { container } = render(
      <MemoryRouter>
        <Sidebar collapsed={false} onToggle={() => {}} />
      </MemoryRouter>,
    );
    expect(await axe(container)).toHaveNoViolations();
  });

  it('Sidebar (collapsed — icon-only links keep accessible names)', async () => {
    const { container } = render(
      <MemoryRouter>
        <Sidebar collapsed onToggle={() => {}} />
      </MemoryRouter>,
    );
    expect(await axe(container)).toHaveNoViolations();
  });

  it('MobileNav (tab bar)', async () => {
    const { container } = render(
      <MemoryRouter>
        <MobileNav />
      </MemoryRouter>,
    );
    expect(await axe(container)).toHaveNoViolations();
  });

  it('MobileNav (open group sheet — menu/menuitem roles)', async () => {
    const { container } = render(
      <MemoryRouter>
        <MobileNav />
      </MemoryRouter>,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Create menu' }));
    // Sheet is now open with role="menu" + role="menuitem" children.
    expect(screen.getByRole('menu', { name: 'Create navigation' })).toBeInTheDocument();
    expect(await axe(container)).toHaveNoViolations();
  });
});
