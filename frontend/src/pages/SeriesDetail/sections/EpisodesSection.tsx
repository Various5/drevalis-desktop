import { useState } from 'react';
import {
  ChevronDown,
  ChevronRight,
  Columns3,
  Film,
  LayoutGrid,
  Play,
  Plus,
  Sparkles,
  Trash2,
  TrendingUp,
} from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { EpisodeCard } from '@/components/episodes/EpisodeCard';
import { EmptyState } from '@/components/ui/EmptyState';
import type { EpisodeListItem } from '@/types';

// Status-grouped "kanban-lite" view with a toggle back to the flat
// grid for users who prefer it. Pulls quick-action buttons into a
// compact toolbar at the top so scattered generate / AI-add /
// trending / delete-all all live in one predictable spot. Empty
// state stays the same.

export interface EpisodesSectionProps {
  episodes: EpisodeListItem[];
  onCreate: () => void;
  onGenerateAllDrafts: () => void;
  onAiAdd: () => void;
  onTrending: () => void;
  onDeleteAll: () => void;
  generatingAllDrafts: boolean;
  addingEpisodesAi: boolean;
  trendingLoading: boolean;
}

// Statuses not in the list (e.g. "editing") land in "Other" so a new
// status added server-side doesn't silently disappear from the UI.
const EPISODE_STATUS_COLUMNS: Array<{
  id: string;
  label: string;
  statuses: string[];
  color: string;
}> = [
  { id: 'draft', label: 'Draft', statuses: ['draft'], color: 'text-txt-secondary' },
  {
    id: 'generating',
    label: 'Generating',
    statuses: ['generating', 'queued'],
    color: 'text-info',
  },
  {
    id: 'review',
    label: 'Review',
    statuses: ['review', 'editing'],
    color: 'text-warning',
  },
  {
    id: 'exported',
    label: 'Exported',
    statuses: ['exported', 'done', 'uploaded'],
    color: 'text-success',
  },
];

export function EpisodesSection({
  episodes,
  onCreate,
  onGenerateAllDrafts,
  onAiAdd,
  onTrending,
  onDeleteAll,
  generatingAllDrafts,
  addingEpisodesAi,
  trendingLoading,
}: EpisodesSectionProps) {
  const [view, setView] = useState<'kanban' | 'grid'>('kanban');
  const [failedOpen, setFailedOpen] = useState(true);

  const draftCount = episodes.filter((ep) => ep.status === 'draft').length;

  const columns = EPISODE_STATUS_COLUMNS.map((col) => ({
    ...col,
    items: episodes.filter((ep) => col.statuses.includes(ep.status)),
  }));
  const failedEpisodes = episodes.filter((ep) => ep.status === 'failed');
  const uncategorized = episodes.filter(
    (ep) =>
      !EPISODE_STATUS_COLUMNS.some((c) => c.statuses.includes(ep.status)) &&
      ep.status !== 'failed',
  );

  return (
    <div>
      <div className="flex items-center justify-between flex-wrap gap-3 mb-4">
        <div>
          <h2 className="text-xl font-semibold text-txt-primary">
            Episodes ({episodes.length})
          </h2>
          <p className="mt-1 text-sm text-txt-tertiary">
            {episodes.length === 0
              ? 'No episodes yet — create one or generate ideas.'
              : `${draftCount} draft${draftCount !== 1 ? 's' : ''} · ${episodes.length - draftCount} in progress or done`}
          </p>
        </div>

        <div className="inline-flex items-center rounded-md border border-border bg-bg-elevated p-0.5 text-xs">
          <button
            type="button"
            onClick={() => setView('kanban')}
            className={[
              'flex items-center gap-1.5 rounded px-2.5 py-1 transition-colors duration-fast',
              view === 'kanban'
                ? 'bg-accent-muted text-accent'
                : 'text-txt-tertiary hover:text-txt-primary',
            ].join(' ')}
            aria-pressed={view === 'kanban'}
            title="Group by status"
          >
            <Columns3 size={12} />
            Kanban
          </button>
          <button
            type="button"
            onClick={() => setView('grid')}
            className={[
              'flex items-center gap-1.5 rounded px-2.5 py-1 transition-colors duration-fast',
              view === 'grid'
                ? 'bg-accent-muted text-accent'
                : 'text-txt-tertiary hover:text-txt-primary',
            ].join(' ')}
            aria-pressed={view === 'grid'}
            title="Flat grid"
          >
            <LayoutGrid size={12} />
            Grid
          </button>
        </div>
      </div>

      <div className="mb-4 flex items-center flex-wrap gap-2">
        <Button variant="primary" size="sm" onClick={onCreate}>
          <Plus size={14} />
          New Episode
        </Button>
        {draftCount > 0 && (
          <Button
            variant="secondary"
            size="sm"
            loading={generatingAllDrafts}
            onClick={onGenerateAllDrafts}
          >
            <Play size={14} />
            Generate {draftCount} draft{draftCount !== 1 ? 's' : ''}
          </Button>
        )}
        <Button
          variant="secondary"
          size="sm"
          loading={addingEpisodesAi}
          onClick={onAiAdd}
        >
          <Sparkles size={14} />
          AI add 5
        </Button>
        <Button
          variant="secondary"
          size="sm"
          loading={trendingLoading}
          onClick={onTrending}
        >
          <TrendingUp size={14} />
          Trending
        </Button>
        {episodes.length > 0 && (
          <Button
            variant="ghost"
            size="sm"
            className="ml-auto text-txt-tertiary hover:text-error"
            onClick={onDeleteAll}
          >
            <Trash2 size={14} />
            Delete All
          </Button>
        )}
      </div>

      {episodes.length === 0 ? (
        <EmptyState
          icon={Film}
          title="No episodes in this series"
          action={
            <Button variant="primary" size="sm" onClick={onCreate}>
              <Plus size={14} />
              Create First Episode
            </Button>
          }
        />
      ) : view === 'kanban' ? (
        <div className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
            {columns.map((col) => (
              <div
                key={col.id}
                className="rounded-lg border border-border bg-bg-elevated/40 p-3 min-h-[180px]"
              >
                <div className="mb-3 flex items-center justify-between">
                  <span
                    className={`text-xs font-semibold uppercase tracking-wider ${col.color}`}
                  >
                    {col.label}
                  </span>
                  <span className="text-[11px] text-txt-tertiary">
                    {col.items.length}
                  </span>
                </div>
                {col.items.length === 0 ? (
                  <p className="text-[11px] text-txt-muted py-6 text-center">
                    Nothing here.
                  </p>
                ) : (
                  <div className="space-y-2">
                    {col.items.map((ep) => (
                      <EpisodeCard key={ep.id} episode={ep} />
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>

          {(failedEpisodes.length > 0 || uncategorized.length > 0) && (
            <div className="rounded-lg border border-error/20 bg-error/5 p-3">
              <button
                type="button"
                onClick={() => setFailedOpen((v) => !v)}
                className="flex w-full items-center justify-between text-left"
              >
                <span className="text-xs font-semibold uppercase tracking-wider text-error">
                  {failedEpisodes.length > 0
                    ? `Failed (${failedEpisodes.length})`
                    : `Other (${uncategorized.length})`}
                </span>
                {failedOpen ? (
                  <ChevronDown size={14} className="text-txt-tertiary" />
                ) : (
                  <ChevronRight size={14} className="text-txt-tertiary" />
                )}
              </button>
              {failedOpen && (
                <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
                  {[...failedEpisodes, ...uncategorized].map((ep) => (
                    <EpisodeCard key={ep.id} episode={ep} />
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {episodes.map((ep) => (
            <EpisodeCard key={ep.id} episode={ep} />
          ))}
        </div>
      )}
    </div>
  );
}
