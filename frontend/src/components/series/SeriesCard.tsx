import { useNavigate } from 'react-router-dom';
import { Film, Clock } from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import type { SeriesListItem } from '@/types';

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface SeriesCardProps {
  series: SeriesListItem;
  className?: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m`;
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

// Deterministic hash → gradient. Avoids the problem of every series
// looking identical in the grid (every card was the same gray Layers
// icon). Each series gets a stable visual identity derived from its
// name — different series, different gradient, every time the page
// renders.
function hashName(name: string): number {
  let h = 0;
  for (let i = 0; i < name.length; i++) {
    h = ((h << 5) - h + name.charCodeAt(i)) | 0;
  }
  return Math.abs(h);
}

const COVER_GRADIENTS = [
  'from-violet-500/30 via-fuchsia-500/20 to-bg-base',
  'from-sky-500/30 via-cyan-500/20 to-bg-base',
  'from-emerald-500/30 via-teal-500/20 to-bg-base',
  'from-amber-500/30 via-orange-500/20 to-bg-base',
  'from-rose-500/30 via-pink-500/20 to-bg-base',
  'from-indigo-500/30 via-blue-500/20 to-bg-base',
] as const;

function coverGradientFor(name: string): string {
  return COVER_GRADIENTS[hashName(name) % COVER_GRADIENTS.length]!;
}

function initialFor(name: string): string {
  const trimmed = name.trim();
  return trimmed ? trimmed[0]!.toUpperCase() : '·';
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

function SeriesCard({ series, className = '' }: SeriesCardProps) {
  const navigate = useNavigate();
  const gradient = coverGradientFor(series.name);
  const initial = initialFor(series.name);

  return (
    <Card
      interactive
      padding="none"
      className={className}
      onClick={() => navigate(`/series/${series.id}`)}
    >
      {/* Cover — deterministic gradient + big monogram. Until the
          backend exposes a per-series cover image / first-episode
          thumbnail, this gives each card a distinct visual identity
          instead of every card looking identical. */}
      <div
        className={`aspect-[16/9] relative overflow-hidden rounded-t-xl bg-gradient-to-br ${gradient}`}
      >
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-6xl font-display font-bold text-white/85 drop-shadow-md select-none">
            {initial}
          </span>
        </div>
        {/* Status pill — only "Active" is wired up today. Once the
            backend tracks paused/archived state this gets driven from
            the series record. */}
        <div className="absolute top-2 right-2">
          <Badge variant="success" dot>
            Active
          </Badge>
        </div>
        <div className="absolute bottom-0 left-0 right-0 h-12 bg-gradient-to-t from-bg-surface to-transparent pointer-events-none" />
      </div>

      {/* Content */}
      <div className="p-3">
        <h3
          className="text-md font-semibold text-txt-primary line-clamp-1"
          title={series.name}
        >
          {series.name}
        </h3>
        {series.description && (
          <p className="mt-1 text-xs text-txt-secondary text-clamp-2">
            {series.description}
          </p>
        )}

        {/* Meta row */}
        <div className="mt-3 flex items-center gap-3 text-xs text-txt-tertiary flex-wrap">
          <span className="inline-flex items-center gap-1">
            <Film size={12} />
            {series.episode_count}{' '}
            {series.episode_count === 1 ? 'episode' : 'episodes'}
          </span>
          <Badge variant="neutral">
            <Clock size={10} />
            {formatDuration(series.target_duration_seconds)}
          </Badge>
        </div>

        <p className="mt-2 text-xs text-txt-tertiary">
          Created {formatDate(series.created_at)}
        </p>
      </div>
    </Card>
  );
}

export { SeriesCard };
export type { SeriesCardProps };
