import { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Plus,
  Film,
  Filter,
  Play,
  Copy,
  Trash2,
  Square,
  Search,
  X,
  CheckSquare,
} from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Select } from '@/components/ui/Select';
import { Input } from '@/components/ui/Input';
import { Textarea } from '@/components/ui/Input';
import { Dialog, DialogFooter } from '@/components/ui/Dialog';
import { Spinner } from '@/components/ui/Spinner';
import { EmptyState } from '@/components/ui/EmptyState';
import { EpisodeCard } from '@/components/episodes/EpisodeCard';
import { useActiveJobsProgress } from '@/lib/websocket';
import { useToast } from '@/components/ui/Toast';
import { episodes as episodesApi } from '@/lib/api';
import { useEpisodes, useSeries, queryKeys } from '@/lib/queries';
import { useQueryClient } from '@tanstack/react-query';
import type {
  EpisodeListItem,
  SeriesListItem,
  EpisodeCreate,
} from '@/types';

// ---------------------------------------------------------------------------
// Status filter tabs
// ---------------------------------------------------------------------------

const STATUS_TABS = [
  { value: '', label: 'All' },
  { value: 'draft', label: 'Draft' },
  { value: 'generating', label: 'Generating' },
  { value: 'review', label: 'Review' },
  { value: 'failed', label: 'Failed' },
] as const;

const SORT_OPTIONS = [
  { value: 'newest', label: 'Newest' },
  { value: 'oldest', label: 'Oldest' },
  { value: 'title', label: 'Title (A→Z)' },
  { value: 'duration', label: 'Duration' },
] as const;
type SortKey = (typeof SORT_OPTIONS)[number]['value'];

// ---------------------------------------------------------------------------
// Episodes List Page
// ---------------------------------------------------------------------------

function EpisodesList() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  // Query-driven loading (Phase 3.3). Mutations elsewhere call
  // ``invalidateQueries`` on the same keys so this list refreshes
  // automatically when an episode is created / deleted / generated.
  const qc = useQueryClient();
  const [statusFilter, setStatusFilter] = useState('');
  const [seriesFilter, setSeriesFilter] = useState('');
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState<SortKey>('newest');

  // Bulk-select mode — toggled from the toolbar. While active, each
  // card renders a checkbox overlay and a sticky bottom action bar
  // shows count + bulk Generate / Delete affordances.
  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkDeleteOpen, setBulkDeleteOpen] = useState(false);

  // Create episode dialog
  const showCreate = searchParams.get('create') === 'true';
  const [createDialogOpen, setCreateDialogOpen] = useState(showCreate);
  const [creating, setCreating] = useState(false);
  const [newSeriesId, setNewSeriesId] = useState('');
  const [newTitle, setNewTitle] = useState('');
  const [newTopic, setNewTopic] = useState('');

  // Delete confirm dialog
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deletingEpisodeId, setDeletingEpisodeId] = useState<string | null>(null);
  const [deletingEpisodeTitle, setDeletingEpisodeTitle] = useState('');
  const [deleting, setDeleting] = useState(false);

  // Duplicate loading
  const [duplicatingId, setDuplicatingId] = useState<string | null>(null);

  // Generate all drafts
  const [generatingAllDrafts, setGeneratingAllDrafts] = useState(false);

  // Toast notifications
  const { toast } = useToast();

  // WebSocket progress
  const { latestByEpisode } = useActiveJobsProgress();

  const episodesQ = useEpisodes({
    series_id: seriesFilter || undefined,
    status: statusFilter || undefined,
  });
  const seriesQ = useSeries();
  const episodesList: EpisodeListItem[] = episodesQ.data ?? [];
  const seriesList: SeriesListItem[] = seriesQ.data ?? [];
  const loading = episodesQ.isPending || seriesQ.isPending;

  // Refetch helper used by mutations declared inline (create / generate
  // / delete). All of them target ``episodes`` so a single invalidation
  // covers everything; the cache key includes the active filters so
  // changing them re-fetches naturally.
  const refetch = useCallback(() => {
    void qc.invalidateQueries({ queryKey: queryKeys.episodes.all });
    void qc.invalidateQueries({ queryKey: queryKeys.series.all });
  }, [qc]);

  useEffect(() => {
    if (episodesQ.error) {
      toast.error('Failed to load episodes', { description: String(episodesQ.error) });
    }
  }, [episodesQ.error, toast]);

  useEffect(() => {
    if (showCreate) setCreateDialogOpen(true);
  }, [showCreate]);

  const seriesOptions = [
    { value: '', label: 'All Series' },
    ...seriesList.map((s) => ({ value: s.id, label: s.name })),
  ];

  const handleCreate = async () => {
    if (!newSeriesId || !newTitle.trim()) return;
    setCreating(true);
    try {
      const payload: EpisodeCreate = {
        series_id: newSeriesId,
        title: newTitle.trim(),
        topic: newTopic.trim() || undefined,
      };
      const ep = await episodesApi.create(payload);
      setCreateDialogOpen(false);
      setNewTitle('');
      setNewTopic('');
      navigate(`/episodes/${ep.id}`);
    } catch (err) {
      toast.error('Failed to create episode', { description: String(err) });
    } finally {
      setCreating(false);
    }
  };

  const handleCancelEpisode = async (episodeId: string) => {
    try {
      await episodesApi.cancel(episodeId);
      refetch();
    } catch (err) {
      toast.error('Failed to cancel episode', { description: String(err) });
    }
  };

  const handleGenerateEpisode = async (episodeId: string) => {
    try {
      await episodesApi.generate(episodeId);
      toast.success('Episode generation started');
      refetch();
    } catch (err) {
      toast.error('Failed to start generation', { description: String(err) });
    }
  };

  const handleDuplicateEpisode = async (episodeId: string) => {
    setDuplicatingId(episodeId);
    try {
      const dup = await episodesApi.duplicate(episodeId);
      navigate(`/episodes/${dup.id}`);
    } catch (err) {
      toast.error('Failed to duplicate episode', { description: String(err) });
    } finally {
      setDuplicatingId(null);
    }
  };

  const handleDeleteEpisode = async () => {
    if (!deletingEpisodeId) return;
    setDeleting(true);
    try {
      await episodesApi.delete(deletingEpisodeId);
      setDeleteDialogOpen(false);
      setDeletingEpisodeId(null);
      toast.success('Episode deleted');
      refetch();
    } catch (err) {
      toast.error('Failed to delete episode', { description: String(err) });
    } finally {
      setDeleting(false);
    }
  };

  const handleGenerateAllDrafts = async () => {
    const drafts = episodesList.filter((ep) => ep.status === 'draft');
    if (drafts.length === 0) return;
    setGeneratingAllDrafts(true);
    try {
      await Promise.all(drafts.map((ep) => episodesApi.generate(ep.id)));
      toast.success('Episode generation started', { description: `${drafts.length} draft${drafts.length === 1 ? '' : 's'} queued` });
      refetch();
    } catch (err) {
      toast.error('Failed to generate all drafts', { description: String(err) });
    } finally {
      setGeneratingAllDrafts(false);
    }
  };

  // Filtered + sorted view — server returns episodes filtered by
  // status/series; search + sort are client-side over that result.
  // Memoise so unrelated state changes (selectMode, dialog flags,
  // bulkBusy, etc.) don't reorder the up-to-500 episode list every
  // render. Deps are explicit: only the inputs that actually affect
  // the output trigger a recompute.
  const visibleEpisodes = useMemo(() => {
    let list = episodesList;
    const q = search.trim().toLowerCase();
    if (q) {
      list = list.filter((ep) => {
        const haystack =
          (ep.title ?? '').toLowerCase() +
          ' ' +
          ((ep as { topic?: string }).topic ?? '').toLowerCase();
        return haystack.includes(q);
      });
    }
    const sorted = [...list];
    switch (sort) {
      case 'newest':
        sorted.sort(
          (a, b) =>
            new Date(b.created_at ?? 0).getTime() -
            new Date(a.created_at ?? 0).getTime(),
        );
        break;
      case 'oldest':
        sorted.sort(
          (a, b) =>
            new Date(a.created_at ?? 0).getTime() -
            new Date(b.created_at ?? 0).getTime(),
        );
        break;
      case 'title':
        sorted.sort((a, b) => (a.title ?? '').localeCompare(b.title ?? ''));
        break;
      case 'duration':
        sorted.sort(
          (a, b) =>
            ((b as { duration_seconds?: number | null }).duration_seconds ?? 0) -
            ((a as { duration_seconds?: number | null }).duration_seconds ?? 0),
        );
        break;
    }
    return sorted;
  }, [episodesList, search, sort]);

  // The status-tab counts also iterate the full list; memoising on the
  // raw list once means each tab render reads from a constant-time map
  // instead of running .filter four times per render.
  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = {
      draft: 0,
      generating: 0,
      review: 0,
      exported: 0,
      failed: 0,
    };
    for (const ep of episodesList) {
      const k = ep.status ?? '';
      if (k in counts) counts[k] = (counts[k] ?? 0) + 1;
    }
    return counts;
  }, [episodesList]);

  // Toggle selection for one card; respect selectMode being on.
  const toggleSelected = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectAllVisible = () => {
    setSelectedIds(new Set(visibleEpisodes.map((ep) => ep.id)));
  };

  const exitSelectMode = () => {
    setSelectMode(false);
    setSelectedIds(new Set());
  };

  const handleBulkGenerate = async () => {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;
    // Only generate items that are draft / failed; everything else is
    // a no-op the backend would reject.
    const eligible = episodesList.filter(
      (ep) =>
        selectedIds.has(ep.id) &&
        (ep.status === 'draft' || ep.status === 'failed'),
    );
    if (eligible.length === 0) {
      toast.error('Nothing to generate', {
        description: 'Selected episodes are not in a draft or failed state.',
      });
      return;
    }
    setBulkBusy(true);
    try {
      await Promise.all(eligible.map((ep) => episodesApi.generate(ep.id)));
      toast.success('Episodes queued', {
        description: `${eligible.length} of ${ids.length} selected enqueued`,
      });
      exitSelectMode();
      refetch();
    } catch (err) {
      toast.error('Bulk generate failed', { description: String(err) });
    } finally {
      setBulkBusy(false);
    }
  };

  const handleBulkDelete = async () => {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;
    setBulkBusy(true);
    try {
      await Promise.all(ids.map((id) => episodesApi.delete(id)));
      toast.success('Episodes deleted', { description: `${ids.length} removed` });
      setBulkDeleteOpen(false);
      exitSelectMode();
      refetch();
    } catch (err) {
      toast.error('Bulk delete failed', { description: String(err) });
    } finally {
      setBulkBusy(false);
    }
  };

  // Count drafts for the "Generate All Draft" button (reads from the
  // memoised counts above instead of running another .filter pass).
  const draftCount = statusCounts.draft ?? 0;

  if (loading) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <Spinner size="lg" />
      </div>
    );
  }

  return (
    <div className="pb-20">
      {/* Header — banner already shows "Episodes"; this row carries the
          subtitle and the page-level CTAs. */}
      <div className="flex items-center justify-between mb-5 gap-3 flex-wrap">
        <p className="text-sm text-txt-secondary">
          Browse and manage all episodes across your series.
        </p>
        <div className="flex items-center gap-2">
          <Button
            variant={selectMode ? 'primary' : 'ghost'}
            size="sm"
            onClick={() => (selectMode ? exitSelectMode() : setSelectMode(true))}
          >
            <CheckSquare size={14} />
            {selectMode ? 'Cancel' : 'Select'}
          </Button>
          {draftCount > 0 && (
            <Button
              variant="secondary"
              loading={generatingAllDrafts}
              onClick={() => void handleGenerateAllDrafts()}
            >
              <Play size={14} />
              Generate All Draft ({draftCount})
            </Button>
          )}
          <Button
            variant="primary"
            onClick={() => setCreateDialogOpen(true)}
          >
            <Plus size={14} />
            New Episode
          </Button>
        </div>
      </div>

      {/* Status filter tabs */}
      <div className="flex items-center gap-1 mb-4 border-b border-white/[0.06]">
        {STATUS_TABS.map((tab) => {
          const isActive = statusFilter === tab.value;
          // For the "All" tab, use total; for specific statuses, use current unfiltered count
          // (We show the count from currently fetched list which respects series filter)
          const count = tab.value === '' ? episodesList.length : statusCounts[tab.value] ?? 0;

          return (
            <button
              key={tab.value}
              onClick={() => setStatusFilter(tab.value)}
              className={[
                'flex items-center gap-1.5 px-4 py-2.5 text-sm font-display font-medium transition-colors duration-fast',
                'border-b-2 -mb-px',
                isActive
                  ? 'border-accent text-accent'
                  : 'border-transparent text-txt-tertiary hover:text-txt-secondary hover:bg-white/[0.04]',
              ].join(' ')}
            >
              {tab.label}
              {count > 0 && (
                <span className={[
                  'text-xs px-1.5 py-0.5 rounded-full',
                  isActive ? 'bg-accent/20 text-accent' : 'bg-bg-hover text-txt-tertiary',
                ].join(' ')}>
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Toolbar — series filter + search + sort. The filter funnels
          the server query (status / series); search and sort act on
          the result set on the client. */}
      <div className="flex items-center gap-2 mb-5 flex-wrap">
        <Filter size={14} className="text-txt-tertiary" />
        <div className="w-48">
          <Select
            options={seriesOptions}
            value={seriesFilter}
            onChange={(e) => setSeriesFilter(e.target.value)}
          />
        </div>
        <div className="relative flex-1 min-w-[180px] max-w-[320px]">
          <Search
            size={13}
            className="absolute left-2.5 top-1/2 -translate-y-1/2 text-txt-tertiary pointer-events-none"
          />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search title or topic..."
            className="w-full h-9 pl-7 pr-7 bg-bg-base border border-white/[0.08] rounded-md text-sm text-txt-primary placeholder:text-txt-tertiary focus:outline-none focus:border-accent/40"
          />
          {search && (
            <button
              onClick={() => setSearch('')}
              className="absolute right-1.5 top-1/2 -translate-y-1/2 p-0.5 rounded hover:bg-white/[0.06] text-txt-tertiary hover:text-txt-primary"
              aria-label="Clear search"
            >
              <X size={12} />
            </button>
          )}
        </div>
        <div className="w-44">
          <Select
            options={SORT_OPTIONS as unknown as { value: string; label: string }[]}
            value={sort}
            onChange={(e) => setSort(e.target.value as SortKey)}
          />
        </div>
        <span className="text-xs text-txt-tertiary ml-auto">
          {visibleEpisodes.length === episodesList.length
            ? `${episodesList.length} ${episodesList.length === 1 ? 'episode' : 'episodes'}`
            : `${visibleEpisodes.length} of ${episodesList.length}`}
        </span>
      </div>

      {/* Grid */}
      {visibleEpisodes.length === 0 ? (
        <EmptyState
          icon={Film}
          title="No episodes found"
          description={
            statusFilter || seriesFilter || search
              ? 'Try clearing your filters or search.'
              : 'Create your first episode to get started.'
          }
          action={
            !statusFilter && !seriesFilter && !search ? (
              <Button variant="primary" onClick={() => setCreateDialogOpen(true)}>
                <Plus size={14} />
                New Episode
              </Button>
            ) : null
          }
        />
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {visibleEpisodes.map((ep) => (
            <div
              key={ep.id}
              className={[
                'relative group',
                selectMode && selectedIds.has(ep.id)
                  ? 'ring-2 ring-accent/60 rounded-xl'
                  : '',
              ].join(' ')}
            >
              <EpisodeCard
                episode={ep}
                stepProgress={latestByEpisode[ep.id]}
              />
              {/* Selection mode — full-card overlay swallows the
                  underlying Card's navigate-on-click and converts it
                  to a selection toggle. The overlay sits above the
                  Card but below the action buttons. */}
              {selectMode && (
                <button
                  type="button"
                  className="absolute inset-0 z-10 cursor-pointer rounded-xl"
                  aria-label={`${selectedIds.has(ep.id) ? 'Unselect' : 'Select'} ${ep.title}`}
                  aria-pressed={selectedIds.has(ep.id)}
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    toggleSelected(ep.id);
                  }}
                />
              )}
              {/* Selection checkbox visual indicator */}
              {selectMode && (
                <div className="absolute top-2 left-2 z-20 pointer-events-none">
                  <span
                    className={[
                      'flex items-center justify-center w-6 h-6 rounded border-2 backdrop-blur-sm',
                      selectedIds.has(ep.id)
                        ? 'bg-accent border-accent text-white'
                        : 'bg-black/40 border-white/40',
                    ].join(' ')}
                  >
                    {selectedIds.has(ep.id) && <CheckSquare size={12} />}
                  </span>
                </div>
              )}
              {/* Per-episode action buttons overlay (hidden in select mode) */}
              <div className={`absolute top-2 right-2 flex items-center gap-1 transition-opacity z-10 ${selectMode ? 'opacity-0 pointer-events-none' : 'opacity-0 group-hover:opacity-100'}`}>
                {(ep.status === 'draft' || ep.status === 'failed') && (
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      void handleGenerateEpisode(ep.id);
                    }}
                    className="p-1.5 rounded bg-accent/90 text-white hover:bg-accent transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
                    title="Generate"
                    aria-label={`Generate ${ep.title}`}
                  >
                    <Play size={12} />
                  </button>
                )}
                {ep.status === 'generating' && (
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      void handleCancelEpisode(ep.id);
                    }}
                    className="p-1.5 rounded bg-red-600/80 text-white hover:bg-red-500 transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-red-300"
                    title="Cancel Generation"
                    aria-label={`Cancel generation of ${ep.title}`}
                  >
                    <Square size={12} />
                  </button>
                )}
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    void handleDuplicateEpisode(ep.id);
                  }}
                  className="p-1.5 rounded bg-black/60 text-white hover:bg-black/80 backdrop-blur-sm transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
                  title="Duplicate"
                  aria-label={`Duplicate ${ep.title}`}
                  disabled={duplicatingId === ep.id}
                >
                  <Copy size={12} />
                </button>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    setDeletingEpisodeId(ep.id);
                    setDeletingEpisodeTitle(ep.title);
                    setDeleteDialogOpen(true);
                  }}
                  className="p-1.5 rounded bg-black/60 text-red-400 hover:bg-red-600/80 hover:text-white backdrop-blur-sm transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-red-400"
                  title="Delete"
                  aria-label={`Delete ${ep.title}`}
                >
                  <Trash2 size={12} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Create Episode Dialog */}
      <Dialog
        open={createDialogOpen}
        onClose={() => setCreateDialogOpen(false)}
        title="Create New Episode"
      >
        <div className="space-y-4">
          <Select
            label="Series"
            placeholder="Select a series..."
            options={seriesList.map((s) => ({ value: s.id, label: s.name }))}
            value={newSeriesId}
            onChange={(e) => setNewSeriesId(e.target.value)}
          />
          <Input
            label="Title"
            placeholder="Episode title..."
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
          />
          <Textarea
            label="Topic"
            placeholder="What should this episode be about?"
            value={newTopic}
            onChange={(e) => setNewTopic(e.target.value)}
          />
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setCreateDialogOpen(false)}>
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={creating}
            disabled={!newSeriesId || !newTitle.trim()}
            onClick={() => void handleCreate()}
          >
            Create Episode
          </Button>
        </DialogFooter>
      </Dialog>

      {/* Floating bulk-action bar — only visible while select mode is on */}
      {selectMode && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-fixed">
          <div className="flex items-center gap-3 bg-bg-elevated/95 backdrop-blur-xl border border-white/[0.1] rounded-full pl-4 pr-2 py-2 shadow-lg">
            <span className="text-sm text-txt-primary font-medium tabular-nums">
              {selectedIds.size} selected
            </span>
            <button
              type="button"
              onClick={selectAllVisible}
              className="text-xs text-accent hover:underline"
            >
              Select all visible
            </button>
            <div className="h-5 w-px bg-white/[0.1]" />
            <Button
              variant="ghost"
              size="sm"
              disabled={selectedIds.size === 0 || bulkBusy}
              onClick={() => void handleBulkGenerate()}
            >
              <Play size={14} /> Generate
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={selectedIds.size === 0 || bulkBusy}
              onClick={() => setBulkDeleteOpen(true)}
              className="text-error hover:bg-error/10"
            >
              <Trash2 size={14} /> Delete
            </Button>
            <Button variant="ghost" size="sm" onClick={exitSelectMode}>
              <X size={14} />
            </Button>
          </div>
        </div>
      )}

      {/* Bulk delete confirmation */}
      <Dialog
        open={bulkDeleteOpen}
        onClose={() => setBulkDeleteOpen(false)}
        title={`Delete ${selectedIds.size} episode${selectedIds.size === 1 ? '' : 's'}?`}
      >
        <p className="text-sm text-txt-secondary">
          This permanently deletes the selected episodes and all generated
          media. This cannot be undone.
        </p>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setBulkDeleteOpen(false)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            loading={bulkBusy}
            onClick={() => void handleBulkDelete()}
          >
            <Trash2 size={14} /> Delete {selectedIds.size}
          </Button>
        </DialogFooter>
      </Dialog>

      {/* Delete Episode Dialog */}
      <Dialog
        open={deleteDialogOpen}
        onClose={() => {
          setDeleteDialogOpen(false);
          setDeletingEpisodeId(null);
        }}
        title="Delete Episode?"
      >
        <p className="text-sm text-txt-secondary">
          This will permanently delete <strong>{deletingEpisodeTitle}</strong> and
          all generated media. This action cannot be undone.
        </p>
        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => {
              setDeleteDialogOpen(false);
              setDeletingEpisodeId(null);
            }}
          >
            Cancel
          </Button>
          <Button
            variant="destructive"
            loading={deleting}
            onClick={() => void handleDeleteEpisode()}
          >
            <Trash2 size={14} />
            Delete Forever
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}

export default EpisodesList;
