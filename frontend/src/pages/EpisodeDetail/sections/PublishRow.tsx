import {
  CalendarDays,
  Upload,
  Search,
  ImageIcon,
  Info,
} from 'lucide-react';
import { Button } from '@/components/ui/Button';
import type { EpisodeStatus } from '@/types';

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface PublishRowProps {
  status: EpisodeStatus;
  action: string;
  youtubeConnected: boolean;
  episodeId: string;
  onOpenSchedule: () => void;
  onOpenUpload: () => void;
  onOpenPublishAll: () => void;
  onOpenSeo: () => void;
  onOpenThumbEditor: () => void;
}

// Statuses that unlock publish actions
const PUBLISH_ELIGIBLE: EpisodeStatus[] = ['review', 'editing', 'exported'];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function PublishRow({
  status,
  action,
  youtubeConnected,
  episodeId: _episodeId,
  onOpenSchedule,
  onOpenUpload,
  onOpenPublishAll,
  onOpenSeo,
  onOpenThumbEditor,
}: PublishRowProps) {
  const eligible = PUBLISH_ELIGIBLE.includes(status);

  if (!eligible) {
    return (
      <div
        className="flex items-center gap-2 px-3 py-2 text-xs text-txt-tertiary bg-bg-elevated/50 rounded-lg border border-border/60"
        role="note"
        aria-label="Publish actions unavailable"
      >
        <Info size={13} className="shrink-0 text-txt-muted" />
        Publish actions become available after generation completes.
      </div>
    );
  }

  return (
    <div
      className="flex items-center gap-2 flex-wrap"
      role="toolbar"
      aria-label="Publish actions"
    >
      <Button
        variant="secondary"
        size="sm"
        onClick={onOpenSchedule}
        aria-label="Schedule this post"
      >
        <CalendarDays size={14} />
        Schedule
      </Button>

      {youtubeConnected && (
        <Button
          variant="secondary"
          size="sm"
          onClick={onOpenUpload}
          aria-label="Upload to YouTube"
        >
          <Upload size={14} />
          Upload to YouTube
        </Button>
      )}

      <Button
        variant="secondary"
        size="sm"
        onClick={onOpenPublishAll}
        aria-label="Publish to all connected platforms"
      >
        <Upload size={14} />
        Publish All
      </Button>

      <Button
        variant="secondary"
        size="sm"
        loading={action === 'generatingSeo'}
        onClick={onOpenSeo}
        aria-label="Generate SEO optimisation for this episode"
      >
        <Search size={14} />
        SEO
      </Button>

      <Button
        variant="secondary"
        size="sm"
        onClick={onOpenThumbEditor}
        aria-label="Edit thumbnail"
      >
        <ImageIcon size={14} />
        Edit thumbnail
      </Button>
    </div>
  );
}
