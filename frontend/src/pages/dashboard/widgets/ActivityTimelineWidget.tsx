import { useNavigate } from 'react-router-dom';
import { Film, LayoutList } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/ui/EmptyState';
import type { EpisodeListItem } from '@/types';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function timeAgo(dateStr: string): string {
  const seconds = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000);
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  if (seconds < 604800) return `${Math.floor(seconds / 86400)}d ago`;
  return new Date(dateStr).toLocaleDateString();
}

const STATUS_COLOR: Record<string, string> = {
  draft: 'var(--color-txt-tertiary)',
  generating: 'var(--color-accent)',
  review: '#34D399',
  editing: '#FBBF24',
  exported: '#34D399',
  failed: '#F87171',
};

// ---------------------------------------------------------------------------
// ActivityItem sub-component
// ---------------------------------------------------------------------------

interface ActivityItemProps {
  episode: EpisodeListItem;
  seriesName: string | undefined;
  onClick: () => void;
}

function ActivityItem({ episode, seriesName, onClick }: ActivityItemProps) {
  const dotColor = STATUS_COLOR[episode.status] ?? 'var(--color-txt-tertiary)';
  return (
    <button
      onClick={onClick}
      className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-white/[0.03] transition-all duration-normal text-left"
      aria-label={`View episode: ${episode.title}`}
    >
      <span
        className="w-2 h-2 rounded-full shrink-0"
        style={{ backgroundColor: dotColor }}
        aria-hidden="true"
      />
      <div className="flex-1 min-w-0">
        <p className="text-sm font-display font-medium text-txt-primary truncate">
          {episode.title}
        </p>
        {seriesName && (
          <p className="text-xs text-txt-tertiary truncate">{seriesName}</p>
        )}
      </div>
      <Badge variant={episode.status} className="shrink-0">
        {episode.status}
      </Badge>
      <span className="text-xs text-txt-tertiary shrink-0 w-20 text-right">
        {timeAgo(episode.created_at)}
      </span>
    </button>
  );
}

// ---------------------------------------------------------------------------
// ActivityTimelineWidget
// ---------------------------------------------------------------------------

interface ActivityTimelineWidgetProps {
  episodes: EpisodeListItem[];
  seriesById: Record<string, string>;
}

export function ActivityTimelineWidget({
  episodes,
  seriesById,
}: ActivityTimelineWidgetProps) {
  const navigate = useNavigate();

  return (
    <Card padding="none">
      <CardHeader className="px-4 pt-4 pb-3">
        <CardTitle>
          <span className="flex items-center gap-2 font-display">
            <LayoutList size={16} className="text-txt-secondary" />
            Recent Activity
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="px-2 pb-3">
        {episodes.length === 0 ? (
          <EmptyState
            icon={Film}
            title="No episodes yet"
            description="Create a series and generate your first episode."
            action={
              <Button size="sm" variant="primary" onClick={() => navigate('/series')}>
                Create a series
              </Button>
            }
          />
        ) : (
          <div className="space-y-0.5">
            {episodes.map((ep) => (
              <ActivityItem
                key={ep.id}
                episode={ep}
                seriesName={seriesById[ep.series_id]}
                onClick={() => navigate(`/episodes/${ep.id}`)}
              />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
