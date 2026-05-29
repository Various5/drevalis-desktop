import { useNavigate } from 'react-router-dom';
import { Film } from 'lucide-react';
import { useTranslation } from 'react-i18next';
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
  const { t } = useTranslation();
  const navigate = useNavigate();

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-display font-semibold text-txt-primary tracking-tight">
          {t('dashboard.widgets.recentEpisodes.heading')}
        </h2>
        <Button variant="ghost" size="sm" onClick={() => navigate('/episodes')}>
          {t('dashboard.widgets.recentEpisodes.viewAll')}
        </Button>
      </div>

      {episodes.length === 0 ? (
        <EmptyState
          icon={Film}
          title={t('dashboard.widgets.recentEpisodes.emptyTitle')}
          description={t('dashboard.widgets.recentEpisodes.emptyDescription')}
          action={
            <div className="flex gap-2 justify-center">
              <Button size="sm" variant="primary" onClick={() => navigate('/series')}>
                {t('dashboard.widgets.recentEpisodes.createSeries')}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => navigate('/help')}>
                {t('dashboard.widgets.recentEpisodes.readHelp')}
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
