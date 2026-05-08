import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { PublishRow } from './PublishRow';
import type { EpisodeStatus } from '@/types';

// ---------------------------------------------------------------------------
// Default props factory
// ---------------------------------------------------------------------------

const defaultProps = {
  action: 'idle' as string,
  youtubeConnected: true,
  episodeId: 'ep-1',
  onOpenSchedule: vi.fn(),
  onOpenUpload: vi.fn(),
  onOpenPublishAll: vi.fn(),
  onOpenSeo: vi.fn(),
  onOpenThumbEditor: vi.fn(),
};

function renderRow(
  status: EpisodeStatus,
  props: Partial<typeof defaultProps> = {},
) {
  return render(
    <PublishRow status={status} {...defaultProps} {...props} />,
  );
}

beforeEach(() => {
  Object.values(defaultProps).forEach((v) => {
    if (typeof v === 'function') vi.mocked(v as ReturnType<typeof vi.fn>).mockClear?.();
  });
});

// ---------------------------------------------------------------------------
// 1. Publish-eligible statuses show the action buttons
// ---------------------------------------------------------------------------

describe('PublishRow — publish-eligible statuses', () => {
  const eligibleStatuses: EpisodeStatus[] = ['review', 'editing', 'exported'];

  for (const s of eligibleStatuses) {
    it(`shows publish buttons for status "${s}"`, () => {
      renderRow(s);
      expect(
        screen.getByRole('button', { name: /schedule this post/i }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: /upload to youtube/i }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: /publish to all connected platforms/i }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: /generate seo/i }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: /edit thumbnail/i }),
      ).toBeInTheDocument();
    });
  }
});

// ---------------------------------------------------------------------------
// 2. Non-eligible statuses show the hint instead
// ---------------------------------------------------------------------------

describe('PublishRow — non-eligible statuses', () => {
  const nonEligibleStatuses: EpisodeStatus[] = [
    'draft',
    'generating',
    'failed',
  ];

  for (const s of nonEligibleStatuses) {
    it(`shows hint note for status "${s}"`, () => {
      renderRow(s);
      expect(
        screen.getByRole('note'),
      ).toBeInTheDocument();
      expect(
        screen.queryByRole('button', { name: /schedule this post/i }),
      ).toBeNull();
    });
  }
});

// ---------------------------------------------------------------------------
// 3. YouTube Upload button hidden when not connected
// ---------------------------------------------------------------------------

describe('PublishRow — YouTube not connected', () => {
  it('hides Upload to YouTube when youtubeConnected is false', () => {
    renderRow('review', { youtubeConnected: false });
    expect(
      screen.queryByRole('button', { name: /upload to youtube/i }),
    ).toBeNull();
    // Other buttons still visible
    expect(
      screen.getByRole('button', { name: /schedule this post/i }),
    ).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// 4. Button callbacks fire correctly
// ---------------------------------------------------------------------------

describe('PublishRow — callbacks', () => {
  it('calls onOpenSchedule when Schedule is clicked', async () => {
    const onOpenSchedule = vi.fn();
    renderRow('review', { onOpenSchedule });
    await userEvent.click(
      screen.getByRole('button', { name: /schedule this post/i }),
    );
    expect(onOpenSchedule).toHaveBeenCalledTimes(1);
  });

  it('calls onOpenUpload when Upload to YouTube is clicked', async () => {
    const onOpenUpload = vi.fn();
    renderRow('review', { onOpenUpload, youtubeConnected: true });
    await userEvent.click(
      screen.getByRole('button', { name: /upload to youtube/i }),
    );
    expect(onOpenUpload).toHaveBeenCalledTimes(1);
  });

  it('calls onOpenPublishAll when Publish All is clicked', async () => {
    const onOpenPublishAll = vi.fn();
    renderRow('review', { onOpenPublishAll });
    await userEvent.click(
      screen.getByRole('button', { name: /publish to all connected platforms/i }),
    );
    expect(onOpenPublishAll).toHaveBeenCalledTimes(1);
  });

  it('calls onOpenSeo when SEO is clicked', async () => {
    const onOpenSeo = vi.fn();
    renderRow('review', { onOpenSeo });
    await userEvent.click(
      screen.getByRole('button', { name: /generate seo/i }),
    );
    expect(onOpenSeo).toHaveBeenCalledTimes(1);
  });

  it('calls onOpenThumbEditor when Edit thumbnail is clicked', async () => {
    const onOpenThumbEditor = vi.fn();
    renderRow('exported', { onOpenThumbEditor });
    await userEvent.click(
      screen.getByRole('button', { name: /edit thumbnail/i }),
    );
    expect(onOpenThumbEditor).toHaveBeenCalledTimes(1);
  });
});

// ---------------------------------------------------------------------------
// 5. SEO button shows loading state
// ---------------------------------------------------------------------------

describe('PublishRow — loading state', () => {
  it('disables SEO button when action is generatingSeo', () => {
    renderRow('review', { action: 'generatingSeo' });
    // Button receives loading=true which sets disabled
    const seoBtn = screen.getByRole('button', { name: /generate seo/i });
    expect(seoBtn).toBeDisabled();
  });
});
