import { useNavigate } from 'react-router-dom';
import { Film } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/ui/EmptyState';
import { EpisodeCard } from '@/components/episodes/EpisodeCard';
import type { EpisodeListItem, ProgressMessage } from '@/types';

// ---------------------------------------------------------------------------
// RecentEpisodesWidget — bottom card-grid of recent episodes on Dashboard
// ---------------------------------------------------------------------------

interface RecentEpisodesWidgetProps {
  episodes: EpisodeListItem[];
  latestByEpisode: Record<string, Record<string, ProgressMessage>>;
}

export function RecentEpisodesWidget({
  episodes,
  latestByEpisode,
}: RecentEpisodesWidgetProps) {
  const navigate = useNavigate();

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-display font-semibold text-txt-primary tracking-tight">
          Recent Episodes
        </h2>
        <Button variant="ghost" size="sm" onClick={() => navigate('/episodes')}>
          View All
        </Button>
      </div>

      {episodes.length === 0 ? (
        <EmptyState
          icon={Film}
          title="No episodes yet"
          description="Create a series and generate your first episode."
          action={
            <div className="flex gap-2 justify-center">
              <Button size="sm" variant="primary" onClick={() => navigate('/series')}>
                Create a series
              </Button>
              <Button size="sm" variant="ghost" onClick={() => navigate('/help')}>
                Read the Help
              </Button>
            </div>
          }
        />
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {episodes.map((ep) => (
            <EpisodeCard
              key={ep.id}
              episode={ep}
              stepProgress={latestByEpisode[ep.id]}
            />
          ))}
        </div>
      )}
    </div>
  );
}
