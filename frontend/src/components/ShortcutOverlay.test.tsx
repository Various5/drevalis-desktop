import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ShortcutOverlay } from './ShortcutOverlay';

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('ShortcutOverlay', () => {
  it('renders nothing when open is false', () => {
    const { container } = render(
      <ShortcutOverlay open={false} onClose={() => {}} />,
    );
    // The component portal-renders to document.body when open. When
    // closed it should add nothing — the React tree returns null AND
    // the portal target stays empty.
    expect(container.firstChild).toBeNull();
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('renders the dialog with all three shortcut groups when open', () => {
    render(<ShortcutOverlay open={true} onClose={() => {}} />);
    const dialog = screen.getByRole('dialog', { name: /keyboard shortcuts/i });
    expect(dialog).toBeInTheDocument();
    // Each group has a heading
    expect(screen.getByText('Global')).toBeInTheDocument();
    expect(screen.getByText('Lists')).toBeInTheDocument();
    expect(screen.getByText('Editor')).toBeInTheDocument();
    // Spot-check a few descriptions to confirm content rendered
    expect(screen.getByText(/Open command palette/)).toBeInTheDocument();
    expect(screen.getByText(/Show this overlay/)).toBeInTheDocument();
    expect(screen.getByText(/Play \/ pause/)).toBeInTheDocument();
  });

  it('marks itself as a modal dialog with proper aria attributes', () => {
    render(<ShortcutOverlay open={true} onClose={() => {}} />);
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(dialog).toHaveAttribute('aria-label', 'Keyboard shortcuts');
  });

  it('closes via the close button click', async () => {
    const onClose = vi.fn();
    render(<ShortcutOverlay open={true} onClose={onClose} />);
    await userEvent.click(
      screen.getByRole('button', { name: /close shortcuts overlay/i }),
    );
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('closes via clicking the backdrop', async () => {
    const onClose = vi.fn();
    render(<ShortcutOverlay open={true} onClose={onClose} />);
    // The dialog's outer wrapper carries the backdrop click handler.
    await userEvent.click(screen.getByRole('dialog'));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('does not close when clicking the inner panel content', async () => {
    const onClose = vi.fn();
    render(<ShortcutOverlay open={true} onClose={onClose} />);
    // Clicking on a kbd or the heading inside the panel should NOT
    // trigger the backdrop close — the inner element calls
    // ``e.stopPropagation()``.
    await userEvent.click(screen.getByRole('heading', { name: /keyboard shortcuts/i }));
    expect(onClose).not.toHaveBeenCalled();
  });

  it('closes on Escape keypress', () => {
    const onClose = vi.fn();
    render(<ShortcutOverlay open={true} onClose={onClose} />);
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('does not close on other keypresses', () => {
    const onClose = vi.fn();
    render(<ShortcutOverlay open={true} onClose={onClose} />);
    fireEvent.keyDown(window, { key: 'Enter' });
    fireEvent.keyDown(window, { key: 'a' });
    fireEvent.keyDown(window, { key: '?' });
    expect(onClose).not.toHaveBeenCalled();
  });

  it('does not bind the Escape listener when open is false', () => {
    const onClose = vi.fn();
    render(<ShortcutOverlay open={false} onClose={onClose} />);
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).not.toHaveBeenCalled();
  });
});
