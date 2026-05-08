import { useNavigate } from 'react-router-dom';
import { Film } from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { JobProgressBar } from '@/components/jobs/JobProgressBar';
import type { EpisodeListItem, ProgressMessage } from '@/types';

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface EpisodeCardProps {
  episode: EpisodeListItem;
  /** Real-time progress keyed by step, if available */
  stepProgress?: Record<string, ProgressMessage>;
  className?: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

function EpisodeCard({
  episode,
  stepProgress,
  className = '',
}: EpisodeCardProps) {
  const navigate = useNavigate();

  const isGenerating = episode.status === 'generating';

  // Cards always render the thumbnail in 16:9. Shorts (9:16) source
  // images are letterboxed on a dark surface via object-contain so the
  // card grid stays uniform — the previous 9:16 cards left a vertical
  // strip of dead space between the image and the title row.
  const isShortsThumb = (episode as { content_format?: string }).content_format === 'shorts';
  const hasFinishedThumb =
    episode.status === 'review' || episode.status === 'exported';

  return (
    <Card
      interactive
      padding="none"
      className={className}
      onClick={() => navigate(`/episodes/${episode.id}`)}
      aria-label={`Episode: ${episode.title} — ${episode.status}`}
    >
      {/* 16:9 Thumbnail area — uniform card heights regardless of the
          underlying episode aspect ratio. */}
      <div className="aspect-video bg-gradient-to-b from-bg-elevated to-bg-base relative overflow-hidden rounded-t-xl thumb-zoom">
        {hasFinishedThumb ? (
          <img
            src={`/storage/episodes/${episode.id}/output/thumbnail.jpg`}
            alt={episode.title}
            loading="lazy"
            decoding="async"
            className={`w-full h-full ${isShortsThumb ? 'object-contain' : 'object-cover'}`}
            onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
          />
        ) : null}
        {!hasFinishedThumb && (
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <Film size={28} className="text-txt-tertiary opacity-40" />
          </div>
        )}
        {/* In-flight progress badge top-right — visible without hovering
            so a glance at the grid shows what's running. */}
        {isGenerating && (
          <div className="absolute top-2 right-2">
            <Badge variant={episode.status} dot>
              generating
            </Badge>
          </div>
        )}
      </div>

      {/* Content */}
      <div className="p-3">
        <div className="flex items-start justify-between gap-2">
          <h4
            className="text-sm font-display font-medium text-txt-primary flex-1 line-clamp-2 leading-snug min-h-[2.5em]"
            title={episode.title}
          >
            {episode.title}
          </h4>
          <div className="flex items-center gap-1 shrink-0">
            {(() => {
              const score = episode.metadata_?.seo?.virality_score;
              if (typeof score !== 'number') return null;
              const variant = score >= 7 ? 'success' : score >= 5 ? 'warning' : 'neutral';
              return (
                <Badge
                  variant={variant}
                  aria-label={`Virality score: ${score} out of 10`}
                >
                  {score}/10
                </Badge>
              );
            })()}
            {!isGenerating && (
              <Badge variant={episode.status} dot>
                {episode.status}
              </Badge>
            )}
          </div>
        </div>

        {episode.topic && (
          <p className="mt-1 text-xs text-txt-tertiary text-truncate">
            {episode.topic}
          </p>
        )}

        {/* Progress bar when generating */}
        {isGenerating && stepProgress && (
          <div className="mt-2">
            <JobProgressBar stepProgress={stepProgress} compact />
          </div>
        )}

        <p className="mt-2 text-xs font-display text-txt-tertiary">
          {formatDate(episode.updated_at)}
        </p>
      </div>
    </Card>
  );
}

export { EpisodeCard };
export type { EpisodeCardProps };
