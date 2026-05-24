import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ConfirmDangerousDialog } from './ConfirmDangerousDialog';

describe('ConfirmDangerousDialog', () => {
  it('gates the confirm button behind the exact confirm word', async () => {
    const onConfirm = vi.fn();
    render(
      <ConfirmDangerousDialog
        open
        onClose={vi.fn()}
        onConfirm={onConfirm}
        title="Delete series?"
        warning="This permanently removes the series and its episodes."
        confirmWord="DELETE"
        confirmLabel="Delete series"
      />,
    );

    const confirmBtn = screen.getByRole('button', { name: 'Delete series' });
    expect(confirmBtn).toBeDisabled();

    const input = screen.getByLabelText('Type DELETE to confirm');
    await userEvent.type(input, 'delete'); // wrong case → still gated
    expect(confirmBtn).toBeDisabled();

    await userEvent.clear(input);
    await userEvent.type(input, 'DELETE');
    expect(confirmBtn).toBeEnabled();

    await userEvent.click(confirmBtn);
    expect(onConfirm).toHaveBeenCalledOnce();
  });

  it('calls onClose from Cancel', async () => {
    const onClose = vi.fn();
    render(
      <ConfirmDangerousDialog
        open
        onClose={onClose}
        onConfirm={vi.fn()}
        title="Enable LAN exposure?"
        warning="Anyone on your network could reach the API."
        confirmWord="EXPOSE"
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('renders nothing when closed', () => {
    render(
      <ConfirmDangerousDialog
        open={false}
        onClose={vi.fn()}
        onConfirm={vi.fn()}
        title="Hidden title"
        warning="x"
        confirmWord="X"
      />,
    );
    expect(screen.queryByText('Hidden title')).toBeNull();
  });
});
