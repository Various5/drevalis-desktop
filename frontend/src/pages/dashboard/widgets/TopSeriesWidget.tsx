import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { Layers, ArrowRight } from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { useEpisodes, useSeries } from '@/lib/queries';
import type { EpisodeListItem, SeriesListItem } from '@/types';

// ---------------------------------------------------------------------------
// TopSeriesWidget — series ranked by completed-episode count
// ---------------------------------------------------------------------------
//
// Pure client-side aggregation over data the dashboard already fetches
// (no extra request). Counts episodes in ``review`` / ``exported``
// status per series and shows the top 3 with their counts.

interface RankedSeries {
  id: string;
  name: string;
  completed: number;
  total: number;
}

function rank(
  episodes: EpisodeListItem[],
  series: SeriesListItem[],
): RankedSeries[] {
  const byId = new Map<string, RankedSeries>();
  for (const s of series) {
    byId.set(s.id, { id: s.id, name: s.name, completed: 0, total: 0 });
  }
  for (const ep of episodes) {
    const row = byId.get(ep.series_id);
    if (!row) continue;
    row.total += 1;
    if (ep.status === 'review' || ep.status === 'exported') {
      row.completed += 1;
    }
  }
  return [...byId.values()]
    .filter((r) => r.total > 0)
    .sort((a, b) => b.completed - a.completed || b.total - a.total)
    .slice(0, 3);
}

export function TopSeriesWidget() {
  const epsQ = useEpisodes();
  const seriesQ = useSeries();

  const top = useMemo(
    () => rank(epsQ.data ?? [], seriesQ.data ?? []),
    [epsQ.data, seriesQ.data],
  );

  return (
    <Card padding="md">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-xs font-display font-semibold text-txt-tertiary uppercase tracking-[0.15em]">
          Top Series
        </h2>
        <Link
          to="/series"
          className="text-xs text-accent hover:underline inline-flex items-center gap-1"
        >
          <Layers size={12} />
          All series
        </Link>
      </div>
      {top.length === 0 ? (
        <p className="text-sm text-txt-tertiary py-3">
          No series yet.{' '}
          <Link to="/series" className="text-accent hover:underline">
            Create your first
          </Link>
          .
        </p>
      ) : (
        <ul className="space-y-2.5">
          {top.map((s, i) => (
            <li key={s.id} className="flex items-center gap-3 text-sm">
              <span className="shrink-0 w-6 h-6 rounded-full bg-bg-elevated flex items-center justify-center text-xs font-semibold text-txt-secondary">
                {i + 1}
              </span>
              <Link
                to={`/series/${s.id}`}
                className="flex-1 min-w-0 truncate text-txt-primary hover:text-accent hover:underline"
              >
                {s.name}
              </Link>
              <span className="shrink-0 text-xs text-txt-tertiary tabular-nums">
                {s.completed}/{s.total} done
              </span>
              <ArrowRight size={12} className="shrink-0 text-txt-tertiary" aria-hidden="true" />
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
