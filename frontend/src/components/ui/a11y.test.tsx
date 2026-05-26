/**
 * Accessibility audit for the shared UI primitives (Phase 5 a11y).
 *
 * Every page in the app composes these primitives, so an axe regression here
 * propagates everywhere — this file is the first line of a11y defence. Each
 * test renders a primitive in a representative configuration and asserts zero
 * axe violations. See ``src/test/axe.ts`` for which rules run.
 */
import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { Inbox } from 'lucide-react';
import { axe } from '@/test/axe';

import { Button } from './Button';
import { Input, Textarea } from './Input';
import { Select } from './Select';
import { Badge } from './Badge';
import { EmptyState } from './EmptyState';
import { Pagination } from './Pagination';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from './Card';
import { FullPageSpinner } from './Spinner';

describe('UI primitives — a11y', () => {
  it('Button: every variant + state has an accessible name', async () => {
    const { container } = render(
      <div>
        <Button variant="primary">Save</Button>
        <Button variant="secondary">Cancel</Button>
        <Button variant="ghost">Dismiss</Button>
        <Button variant="destructive">Delete</Button>
        <Button loading>Saving</Button>
        <Button disabled>Unavailable</Button>
      </div>,
    );
    expect(await axe(container)).toHaveNoViolations();
  });

  it('Input: label is programmatically associated', async () => {
    const { container } = render(
      <Input label="Email address" hint="We never share it." placeholder="you@example.com" />,
    );
    expect(await axe(container)).toHaveNoViolations();
  });

  it('Input: error message does not break the label association', async () => {
    const { container } = render(<Input label="Password" error="Too short" type="password" />);
    expect(await axe(container)).toHaveNoViolations();
  });

  it('Textarea: label is programmatically associated', async () => {
    const { container } = render(<Textarea label="Description" hint="Markdown supported." />);
    expect(await axe(container)).toHaveNoViolations();
  });

  it('Select: label + options are accessible', async () => {
    const { container } = render(
      <Select
        label="Voice provider"
        placeholder="Pick one"
        options={[
          { value: 'elevenlabs', label: 'ElevenLabs' },
          { value: 'openai', label: 'OpenAI' },
        ]}
      />,
    );
    expect(await axe(container)).toHaveNoViolations();
  });

  it('Badge: status pill has no violations', async () => {
    const { container } = render(
      <div>
        <Badge variant="success">Exported</Badge>
        <Badge variant="error" dot>
          Failed
        </Badge>
        <Badge variant="generating">Generating</Badge>
      </div>,
    );
    expect(await axe(container)).toHaveNoViolations();
  });

  it('EmptyState: heading + status role are valid', async () => {
    const { container } = render(
      <EmptyState
        icon={Inbox}
        title="No episodes yet"
        description="Create your first episode to get started."
        action={<Button>New episode</Button>}
      />,
    );
    expect(await axe(container)).toHaveNoViolations();
  });

  it('Pagination: nav landmark + labelled controls', async () => {
    const { container } = render(
      <Pagination page={3} totalPages={20} onPageChange={() => {}} />,
    );
    expect(await axe(container)).toHaveNoViolations();
  });

  it('Card: static content card', async () => {
    const { container } = render(
      <Card>
        <CardHeader>
          <CardTitle>Weekly stats</CardTitle>
        </CardHeader>
        <CardDescription>Your channel performance this week.</CardDescription>
        <CardContent>1,204 views</CardContent>
      </Card>,
    );
    expect(await axe(container)).toHaveNoViolations();
  });

  it('Card: interactive (role=button) card is keyboard-operable', async () => {
    const { container } = render(
      <Card interactive onClick={() => {}}>
        <CardTitle>Open episode</CardTitle>
      </Card>,
    );
    expect(await axe(container)).toHaveNoViolations();
  });

  it('FullPageSpinner: loading indicator has no violations', async () => {
    const { container } = render(<FullPageSpinner />);
    expect(await axe(container)).toHaveNoViolations();
  });
});
