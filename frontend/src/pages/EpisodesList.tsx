import { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Trans, useTranslation } from 'react-i18next';
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
  AlertTriangle,
  ExternalLink,
} from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Select } from '@/components/ui/Select';
import { Input } from '@/components/ui/Input';
import { Textarea } from '@/components/ui/Input';
import { Dialog, DialogFooter } from '@/components/ui/Dialog';
import { Skeleton } from '@/components/ui/Skeleton';
import { CardGridSkeleton } from '@/components/ui/Skeletons';
import { EmptyState } from '@/components/ui/EmptyState';
import { EpisodeCard } from '@/components/episodes/EpisodeCard';
import { EpisodeTrashDialog } from '@/components/episodes/EpisodeTrashDialog';
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
// Title-conflict warning — calls /youtube/check-title-conflict with a
// 400ms debounce so the user gets fast feedback without one API hit
// per keystroke. Surfaces inline above the topic field so the warning
// is impossible to miss before clicking Create.
// ---------------------------------------------------------------------------

interface TitleMatch {
  video_id: string;
  youtube_video_id: string;
  title: string;
  similarity: number;
  is_short: boolean;
  url: string;
}

function TitleConflictWarning({ title }: { title: string }) {
  const { t } = useTranslation();
  const [matches, setMatches] = useState<TitleMatch[]>([]);
  const [loading, setLoading] = useState(false);
  const trimmed = title.trim();

  useEffect(() => {
    if (trimmed.length < 6) {
      setMatches([]);
      return;
    }
    setLoading(true);
    const handle = setTimeout(async () => {
      try {
        const res = await fetch('/api/v1/youtube/check-title-conflict', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ title: trimmed, threshold: 0.7 }),
        });
        if (!res.ok) {
          setMatches([]);
        } else {
          const j = (await res.json()) as { matches: TitleMatch[] };
          setMatches(j.matches ?? []);
        }
      } catch {
        setMatches([]);
      } finally {
        setLoading(false);
      }
    }, 400);
    return () => clearTimeout(handle);
  }, [trimmed]);

  if (loading || matches.length === 0) return null;

  return (
    <div className="rounded-md border border-warning/40 bg-warning/5 p-3">
      <div className="flex items-start gap-2">
        <AlertTriangle size={14} className="text-warning shrink-0 mt-0.5" />
        <div className="flex-1 min-w-0">
          <p className="text-xs font-medium text-warning">
            {t('episodes.titleConflict.title', { count: matches.length })}
          </p>
          <ul className="mt-1.5 space-y-1">
            {matches.map((m) => (
              <li
                key={m.video_id}
                className="flex items-center justify-between gap-2 text-xs"
              >
                <a
                  href={m.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-txt-secondary truncate hover:text-accent inline-flex items-center gap-1 min-w-0"
                >
                  <span className="truncate">{m.title}</span>
                  <ExternalLink size={10} className="shrink-0 opacity-60" />
                </a>
                <span className="text-[10px] tabular-nums text-txt-tertiary shrink-0">
                  {t('episodes.titleConflict.matchSuffix', { pct: Math.round(m.similarity * 100) })}
                  {m.is_short ? t('episodes.titleConflict.shortSuffix') : ''}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Status / sort tab identifiers — labels come from i18n
// ---------------------------------------------------------------------------

const STATUS_TAB_KEYS = ['', 'draft', 'generating', 'review', 'failed'] as const;
type StatusTabKey = (typeof STATUS_TAB_KEYS)[number];

const SORT_KEYS = ['newest', 'oldest', 'title', 'duration'] as const;
type SortKey = (typeof SORT_KEYS)[number];

// ---------------------------------------------------------------------------
// Episodes List Page
// ---------------------------------------------------------------------------

function EpisodesList() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  // Query-driven loading (Phase 3.3). Mutations elsewhere call
  // ``invalidateQueries`` on the same keys so this list refreshes
  // automatically when an episode is created / deleted / generated.
  const qc = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<StatusTabKey>('');
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
  const [trashOpen, setTrashOpen] = useState(false);

  // Create episode dialog
  const showCreate = searchParams.get('create') === 'true';
  const [createDialogOpen, setCreateDialogOpen] = useState(showCreate);
  const [creating, setCreating] = useState(false);
  const [newSeriesId, setNewSeriesId] = useState(searchParams.get('series') ?? '');
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
      toast.error(t('episodes.loadFailed'), { description: String(episodesQ.error) });
    }
  }, [episodesQ.error, toast, t]);

  useEffect(() => {
    if (showCreate) setCreateDialogOpen(true);
  }, [showCreate]);

  const seriesOptions = [
    { value: '', label: t('episodes.allSeries') },
    ...seriesList.map((s) => ({ value: s.id, label: s.name })),
  ];

  const sortOptions = SORT_KEYS.map((value) => ({
    value,
    label: t(`episodes.sort.${value}`),
  }));

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
      toast.error(t('episodes.toasts.createFailed'), { description: String(err) });
    } finally {
      setCreating(false);
    }
  };

  const handleCancelEpisode = async (episodeId: string) => {
    try {
      await episodesApi.cancel(episodeId);
      refetch();
    } catch (err) {
      toast.error(t('episodes.toasts.cancelFailed'), { description: String(err) });
    }
  };

  const handleGenerateEpisode = async (episodeId: string) => {
    try {
      await episodesApi.generate(episodeId);
      toast.success(t('episodes.toasts.generationStarted'));
      refetch();
    } catch (err) {
      toast.error(t('episodes.toasts.generationFailed'), { description: String(err) });
    }
  };

  const handleDuplicateEpisode = async (episodeId: string) => {
    setDuplicatingId(episodeId);
    try {
      const dup = await episodesApi.duplicate(episodeId);
      navigate(`/episodes/${dup.id}`);
    } catch (err) {
      toast.error(t('episodes.toasts.duplicateFailed'), { description: String(err) });
    } finally {
      setDuplicatingId(null);
    }
  };

  const handleDeleteEpisode = async () => {
    if (!deletingEpisodeId) return;
    const deletedId = deletingEpisodeId;
    const deletedTitle = deletingEpisodeTitle;
    setDeleting(true);
    try {
      await episodesApi.delete(deletedId);
      setDeleteDialogOpen(false);
      setDeletingEpisodeId(null);
      toast.success(t('episodes.toasts.deletedToast'), {
        description: deletedTitle || undefined,
        action: {
          label: t('episodes.toasts.undo'),
          onClick: () => {
            void (async () => {
              try {
                await episodesApi.restore(deletedId);
                refetch();
                toast.success(t('episodes.toasts.restoredToast'));
              } catch (err) {
                toast.error(t('episodes.toasts.restoreFailed'), { description: String(err) });
              }
            })();
          },
        },
      });
      refetch();
    } catch (err) {
      toast.error(t('episodes.toasts.deleteFailed'), { description: String(err) });
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
      toast.success(t('episodes.toasts.generationStarted'), {
        description: t('episodes.toasts.draftsQueued', { count: drafts.length }),
      });
      refetch();
    } catch (err) {
      toast.error(t('episodes.toasts.generateAllFailed'), { description: String(err) });
    } finally {
      setGeneratingAllDrafts(false);
    }
  };

  // Filtered + sorted view — server returns episodes filtered by
  // status/series; search + sort are client-side over that result.
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
      toast.error(t('episodes.toasts.nothingToGenerate'), {
        description: t('episodes.toasts.nothingToGenerateDesc'),
      });
      return;
    }
    setBulkBusy(true);
    try {
      await Promise.all(eligible.map((ep) => episodesApi.generate(ep.id)));
      toast.success(t('episodes.toasts.episodesQueued'), {
        description: t('episodes.toasts.episodesQueuedDesc', {
          eligible: eligible.length,
          total: ids.length,
        }),
      });
      exitSelectMode();
      refetch();
    } catch (err) {
      toast.error(t('episodes.toasts.bulkGenerateFailed'), { description: String(err) });
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
      toast.success(t('episodes.toasts.episodesDeleted'), {
        description: t('episodes.toasts.episodesDeletedDesc', { count: ids.length }),
        action: {
          label: t('episodes.toasts.undo'),
          onClick: () => {
            void (async () => {
              try {
                await Promise.all(ids.map((id) => episodesApi.restore(id)));
                refetch();
                toast.success(t('episodes.toasts.restoredToast'), {
                  description: t('episodes.toasts.episodesRestoredDesc', { count: ids.length }),
                });
              } catch (err) {
                toast.error(t('episodes.toasts.restoreFailed'), { description: String(err) });
              }
            })();
          },
        },
      });
      setBulkDeleteOpen(false);
      exitSelectMode();
      refetch();
    } catch (err) {
      toast.error(t('episodes.toasts.bulkDeleteFailed'), { description: String(err) });
    } finally {
      setBulkBusy(false);
    }
  };

  // Count drafts for the "Generate All Draft" button (reads from the
  // memoised counts above instead of running another .filter pass).
  const draftCount = statusCounts.draft ?? 0;

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-48" rounded="md" />
        <CardGridSkeleton count={8} gridClassName="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4" />
      </div>
    );
  }

  return (
    <div className="pb-20">
      {/* Header — banner already shows "Episodes"; this row carries the
          subtitle and the page-level CTAs. */}
      <div className="flex items-center justify-between mb-5 gap-3 flex-wrap">
        <p className="text-sm text-txt-secondary">
          {t('episodes.subtitle')}
        </p>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setTrashOpen(true)}
            title={t('episodes.trashTitle')}
          >
            <Trash2 size={14} />
            {t('episodes.trash')}
          </Button>
          <Button
            variant={selectMode ? 'primary' : 'ghost'}
            size="sm"
            onClick={() => (selectMode ? exitSelectMode() : setSelectMode(true))}
          >
            <CheckSquare size={14} />
            {selectMode ? t('episodes.cancel') : t('episodes.select')}
          </Button>
          {draftCount > 0 && (
            <Button
              variant="secondary"
              loading={generatingAllDrafts}
              onClick={() => void handleGenerateAllDrafts()}
            >
              <Play size={14} />
              {t('episodes.generateAllDraft', { count: draftCount })}
            </Button>
          )}
          <Button
            variant="primary"
            onClick={() => setCreateDialogOpen(true)}
          >
            <Plus size={14} />
            {t('episodes.newEpisode')}
          </Button>
        </div>
      </div>

      {/* Status filter tabs */}
      <div className="flex items-center gap-1 mb-4 border-b border-white/[0.06]">
        {STATUS_TAB_KEYS.map((key) => {
          const isActive = statusFilter === key;
          // For the "All" tab, use total; for specific statuses, use the
          // memoised counts map.
          const count = key === '' ? episodesList.length : statusCounts[key] ?? 0;
          const label = key === ''
            ? t('episodes.filters.all')
            : t(`episodes.filters.${key}`);
          return (
            <button
              key={key || 'all'}
              onClick={() => setStatusFilter(key)}
              className={[
                'flex items-center gap-1.5 px-4 py-2.5 text-sm font-display font-medium transition-colors duration-fast',
                'border-b-2 -mb-px',
                isActive
                  ? 'border-accent text-accent'
                  : 'border-transparent text-txt-tertiary hover:text-txt-secondary hover:bg-white/[0.04]',
              ].join(' ')}
            >
              {label}
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

      {/* Toolbar — series filter + search + sort. */}
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
            placeholder={t('episodes.searchPlaceholder')}
            className="w-full h-9 pl-7 pr-7 bg-bg-base border border-white/[0.08] rounded-md text-sm text-txt-primary placeholder:text-txt-tertiary focus:outline-none focus:border-accent/40"
          />
          {search && (
            <button
              onClick={() => setSearch('')}
              className="absolute right-1.5 top-1/2 -translate-y-1/2 p-0.5 rounded hover:bg-white/[0.06] text-txt-tertiary hover:text-txt-primary"
              aria-label={t('episodes.clearSearch')}
            >
              <X size={12} />
            </button>
          )}
        </div>
        <div className="w-44">
          <Select
            options={sortOptions}
            value={sort}
            onChange={(e) => setSort(e.target.value as SortKey)}
          />
        </div>
        <span className="text-xs text-txt-tertiary ml-auto">
          {visibleEpisodes.length === episodesList.length
            ? episodesList.length === 1
              ? t('episodes.countSingular', { count: episodesList.length })
              : t('episodes.countPlural', { count: episodesList.length })
            : t('episodes.countFiltered', { shown: visibleEpisodes.length, total: episodesList.length })}
        </span>
      </div>

      {/* Grid */}
      {visibleEpisodes.length === 0 ? (
        <EmptyState
          icon={Film}
          title={t('episodes.empty.title')}
          description={
            statusFilter || seriesFilter || search
              ? t('episodes.empty.withFilters')
              : t('episodes.empty.noFilters')
          }
          action={
            !statusFilter && !seriesFilter && !search ? (
              <Button variant="primary" onClick={() => setCreateDialogOpen(true)}>
                <Plus size={14} />
                {t('episodes.newEpisode')}
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
                  to a selection toggle. */}
              {selectMode && (
                <button
                  type="button"
                  className="absolute inset-0 z-10 cursor-pointer rounded-xl"
                  aria-label={
                    selectedIds.has(ep.id)
                      ? t('episodes.actions.unselectAria', { title: ep.title })
                      : t('episodes.actions.selectAria', { title: ep.title })
                  }
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
                    title={t('episodes.actions.generate')}
                    aria-label={t('episodes.actions.generateAria', { title: ep.title })}
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
                    title={t('episodes.actions.cancelGenerationTitle')}
                    aria-label={t('episodes.actions.cancelGenerationAria', { title: ep.title })}
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
                  title={t('episodes.actions.duplicateTitle')}
                  aria-label={t('episodes.actions.duplicateAria', { title: ep.title })}
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
                  title={t('episodes.actions.deleteTitle')}
                  aria-label={t('episodes.actions.deleteAria', { title: ep.title })}
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
        title={t('episodes.create.title')}
      >
        <div className="space-y-4">
          <Select
            label={t('episodes.create.seriesLabel')}
            placeholder={t('episodes.create.seriesPlaceholder')}
            options={seriesList.map((s) => ({ value: s.id, label: s.name }))}
            value={newSeriesId}
            onChange={(e) => setNewSeriesId(e.target.value)}
          />
          <Input
            label={t('episodes.create.titleLabel')}
            placeholder={t('episodes.create.titlePlaceholder')}
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
          />
          {/* Debounced title-similarity check against every video already
              on the connected YouTube channels. */}
          <TitleConflictWarning title={newTitle} />
          <Textarea
            label={t('episodes.create.topicLabel')}
            placeholder={t('episodes.create.topicPlaceholder')}
            value={newTopic}
            onChange={(e) => setNewTopic(e.target.value)}
          />
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setCreateDialogOpen(false)}>
            {t('episodes.create.cancel')}
          </Button>
          <Button
            variant="primary"
            loading={creating}
            disabled={!newSeriesId || !newTitle.trim()}
            onClick={() => void handleCreate()}
          >
            {t('episodes.create.submit')}
          </Button>
        </DialogFooter>
      </Dialog>

      {/* Floating bulk-action bar — only visible while select mode is on */}
      {selectMode && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-fixed">
          <div className="flex items-center gap-3 bg-bg-elevated/95 backdrop-blur-xl border border-white/[0.1] rounded-full pl-4 pr-2 py-2 shadow-lg">
            <span className="text-sm text-txt-primary font-medium tabular-nums">
              {t('episodes.bulkBar.selectedCount', { count: selectedIds.size })}
            </span>
            <button
              type="button"
              onClick={selectAllVisible}
              className="text-xs text-accent hover:underline"
            >
              {t('episodes.bulkBar.selectAllVisible')}
            </button>
            <div className="h-5 w-px bg-white/[0.1]" />
            <Button
              variant="ghost"
              size="sm"
              disabled={selectedIds.size === 0 || bulkBusy}
              onClick={() => void handleBulkGenerate()}
            >
              <Play size={14} /> {t('episodes.bulkBar.generate')}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={selectedIds.size === 0 || bulkBusy}
              onClick={() => setBulkDeleteOpen(true)}
              className="text-error hover:bg-error/10"
            >
              <Trash2 size={14} /> {t('episodes.bulkBar.delete')}
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
        title={t('episodes.bulkDelete.title', { count: selectedIds.size })}
      >
        <p className="text-sm text-txt-secondary">
          {t('episodes.bulkDelete.body')}
        </p>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setBulkDeleteOpen(false)}>
            {t('episodes.bulkDelete.cancel')}
          </Button>
          <Button
            variant="destructive"
            loading={bulkBusy}
            onClick={() => void handleBulkDelete()}
          >
            <Trash2 size={14} /> {t('episodes.bulkDelete.confirm', { count: selectedIds.size })}
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
        title={t('episodes.delete.title')}
      >
        <p className="text-sm text-txt-secondary">
          <Trans
            i18nKey="episodes.delete.body"
            values={{ title: deletingEpisodeTitle }}
            components={{ 1: <strong /> }}
          />
        </p>
        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => {
              setDeleteDialogOpen(false);
              setDeletingEpisodeId(null);
            }}
          >
            {t('episodes.delete.cancel')}
          </Button>
          <Button
            variant="destructive"
            loading={deleting}
            onClick={() => void handleDeleteEpisode()}
          >
            <Trash2 size={14} />
            {t('episodes.delete.confirm')}
          </Button>
        </DialogFooter>
      </Dialog>

      <EpisodeTrashDialog open={trashOpen} onClose={() => setTrashOpen(false)} onChanged={refetch} />
    </div>
  );
}

export default EpisodesList;
