import { useEffect, useMemo, useRef, useState, useCallback, type ReactNode } from 'react';
import { Settings2, Check } from 'lucide-react';
import { SetupChecklist } from '@/components/SetupChecklist';
import { SystemHealthCard } from '@/components/SystemHealthCard';
import { Button } from '@/components/ui/Button';
import { Spinner } from '@/components/ui/Spinner';
import { useToast } from '@/components/ui/Toast';
import { ApiError, formatError } from '@/lib/api';
import { useActiveJobsProgress } from '@/lib/websocket';
import {
  useActiveJobs,
  useEpisodes,
  useRecentEpisodes,
  useSeries,
} from '@/lib/queries';
import type { EpisodeListItem, GenerationJobListItem, ProgressMessage } from '@/types';

import { useDashboardLayout } from './useDashboardLayout';
import { WidgetWrapper } from './WidgetWrapper';
import { DashboardCustomizeDialog } from './DashboardCustomizeDialog';
import { StatCardsWidget } from './widgets/StatCardsWidget';
import { QuickActionsWidget } from './widgets/QuickActionsWidget';
import { ActivityTimelineWidget } from './widgets/ActivityTimelineWidget';
import { RecentEpisodesWidget } from './widgets/RecentEpisodesWidget';
import { ActiveJobsWidget } from './widgets/ActiveJobsWidget';
import { UpcomingPostsWidget } from './widgets/UpcomingPostsWidget';
import { TopSeriesWidget } from './widgets/TopSeriesWidget';
import { QuotaUsageWidget } from './widgets/QuotaUsageWidget';
import { WIDGET_LABELS, type WidgetId } from './types';

// =============================================================================
// Dashboard Page — customizable widget layout with drag-drop reorder + show/hide
// =============================================================================

// ---------------------------------------------------------------------------
// Widget registry — maps widget id → render function receiving data props.
// The render functions are pure so the registry is defined outside the
// component to avoid recreation on every render.
// ---------------------------------------------------------------------------

interface WidgetDataProps {
  totalEpisodes: number;
  completedCount: number;
  failedCount: number;
  totalSeries: number;
  seriesList: { id: string }[];
  activityEpisodes: EpisodeListItem[];
  seriesById: Record<string, string>;
  recentEpisodes: EpisodeListItem[];
  latestByEpisode: Record<string, Record<string, ProgressMessage>>;
  activeJobs: GenerationJobListItem[];
}

type WidgetRenderer = (props: WidgetDataProps) => ReactNode;

const WIDGET_REGISTRY: Record<WidgetId, WidgetRenderer> = {
  'setup-checklist': () => <SetupChecklist />,
  'system-health': () => <SystemHealthCard />,
  'stat-cards': ({ totalEpisodes, completedCount, failedCount, totalSeries }) => (
    <StatCardsWidget
      totalEpisodes={totalEpisodes}
      completedCount={completedCount}
      failedCount={failedCount}
      totalSeries={totalSeries}
    />
  ),
  'quick-actions': ({ seriesList }) => <QuickActionsWidget seriesList={seriesList} />,
  'activity-timeline': ({ activityEpisodes, seriesById }) => (
    <ActivityTimelineWidget episodes={activityEpisodes} seriesById={seriesById} />
  ),
  'recent-episodes': ({ recentEpisodes, latestByEpisode }) => (
    <RecentEpisodesWidget episodes={recentEpisodes} latestByEpisode={latestByEpisode} />
  ),
  'active-jobs': ({ activeJobs, latestByEpisode }) => (
    <ActiveJobsWidget activeJobs={activeJobs} latestByEpisode={latestByEpisode} />
  ),
  // Self-contained widgets — fetch their own data, no shared deps.
  'upcoming-posts': () => <UpcomingPostsWidget />,
  'top-series': () => <TopSeriesWidget />,
  'quota-usage': () => <QuotaUsageWidget />,
};

// ---------------------------------------------------------------------------
// Dashboard component
// ---------------------------------------------------------------------------

function Dashboard() {
  const { toast } = useToast();

  // --- WebSocket progress ---
  const { latestByEpisode } = useActiveJobsProgress();

  // --- Data queries ---
  const recentQ = useRecentEpisodes(8);
  const activityQ = useRecentEpisodes(10);
  const seriesQ = useSeries();
  const allEpsQ = useEpisodes();
  const hasActive = Object.keys(latestByEpisode).length > 0;
  const activeJobsQ = useActiveJobs({ hasActive });

  const recentEpisodes: EpisodeListItem[] = recentQ.data ?? [];
  const activityEpisodes = activityQ.data ?? [];
  const seriesList = seriesQ.data ?? [];
  const activeJobs = activeJobsQ.data ?? [];
  const allEpisodes = allEpsQ.data ?? [];
  const loading =
    recentQ.isPending ||
    activityQ.isPending ||
    seriesQ.isPending ||
    allEpsQ.isPending;

  // Error toast — collapse to one burst per error appearance.
  const lastErrShown = useRef(false);
  useEffect(() => {
    const err =
      recentQ.error ||
      activityQ.error ||
      seriesQ.error ||
      allEpsQ.error ||
      activeJobsQ.error;
    if (!err) {
      lastErrShown.current = false;
      return;
    }
    if (err instanceof ApiError && err.status === 402) return;
    if (!lastErrShown.current) {
      toast.error('Failed to load dashboard data', { description: formatError(err) });
      lastErrShown.current = true;
    }
  }, [
    recentQ.error,
    activityQ.error,
    seriesQ.error,
    allEpsQ.error,
    activeJobsQ.error,
    toast,
  ]);

  // --- Stats (memoised — WS messages re-render at pipeline-progress cadence) ---
  const totalEpisodes = allEpisodes.length;
  const { completedCount, failedCount } = useMemo(() => {
    let completed = 0;
    let failed = 0;
    for (const e of allEpisodes) {
      if (e.status === 'review' || e.status === 'exported') completed += 1;
      else if (e.status === 'failed') failed += 1;
    }
    return { completedCount: completed, failedCount: failed };
  }, [allEpisodes]);
  const totalSeries = seriesList.length;

  // Series lookup map for activity timeline
  const seriesById = useMemo(
    () => Object.fromEntries(seriesList.map((s) => [s.id, s.name])),
    [seriesList],
  );

  // --- Layout prefs ---
  const { layout, isLoading: layoutLoading, moveWidget, hideWidget, showWidget, moveWidgetByDelta } =
    useDashboardLayout();

  // --- Edit mode ---
  const [editMode, setEditMode] = useState(false);
  const [mobileDialogOpen, setMobileDialogOpen] = useState(false);

  // --- Drag-and-drop state ---
  const dragIndexRef = useRef<number | null>(null);
  const [dropTargetIndex, setDropTargetIndex] = useState<number | null>(null);

  const handleDragStart = useCallback((index: number) => {
    dragIndexRef.current = index;
  }, []);

  const handleDragOver = useCallback((_e: React.DragEvent, index: number) => {
    setDropTargetIndex(index);
  }, []);

  const handleDrop = useCallback(
    (toIndex: number) => {
      const fromIndex = dragIndexRef.current;
      if (fromIndex !== null && fromIndex !== toIndex) {
        moveWidget(fromIndex, toIndex);
      }
      dragIndexRef.current = null;
      setDropTargetIndex(null);
    },
    [moveWidget],
  );

  const handleDragEnd = useCallback(() => {
    dragIndexRef.current = null;
    setDropTargetIndex(null);
  }, []);

  // --- Widget data props (stable object so WIDGET_REGISTRY calls don't
  //     proliferate per-widget memos; the renders are cheap enough) ---
  const widgetDataProps: WidgetDataProps = {
    totalEpisodes,
    completedCount,
    failedCount,
    totalSeries,
    seriesList,
    activityEpisodes,
    seriesById,
    recentEpisodes,
    latestByEpisode,
    activeJobs,
  };

  // --- Loading states ---
  if (loading || layoutLoading) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <Spinner size="lg" />
      </div>
    );
  }

  // active-jobs auto-shows when there are active jobs (even if hidden in prefs).
  // We splice it in front of the visible list without mutating prefs.
  const visibleWidgets = [...layout.widgets];
  const hasActiveJobs = activeJobs.length > 0;
  if (hasActiveJobs && !visibleWidgets.includes('active-jobs')) {
    // Insert before 'recent-episodes' if present, otherwise append.
    const recentIdx = visibleWidgets.indexOf('recent-episodes');
    if (recentIdx >= 0) {
      visibleWidgets.splice(recentIdx, 0, 'active-jobs');
    } else {
      visibleWidgets.push('active-jobs');
    }
  }

  const hiddenWidgets = layout.hidden.filter(
    // Don't show active-jobs in the "hidden" tray when there are no active jobs.
    (id) => !(id === 'active-jobs' && !hasActiveJobs),
  );

  return (
    <div className="space-y-6">
      {/* Top bar: customize button */}
      <div className="flex items-center justify-end">
        {!editMode ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              // On mobile open the dialog, on desktop enter inline edit mode.
              // We detect viewport via JS since CSS media queries don't affect
              // JS logic — check innerWidth at click time (not on render).
              if (window.innerWidth < 768) {
                setMobileDialogOpen(true);
              } else {
                setEditMode(true);
              }
            }}
            aria-label="Customize dashboard layout"
          >
            <Settings2 size={14} />
            Customize
          </Button>
        ) : (
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setEditMode(false)}
            aria-label="Exit customize mode"
          >
            <Check size={14} />
            Done
          </Button>
        )}
      </div>

      {/* Visible widgets */}
      <div className="space-y-6">
        {visibleWidgets.map((id, index) => {
          const renderer = WIDGET_REGISTRY[id];
          return (
            <WidgetWrapper
              key={id}
              id={id}
              index={index}
              editMode={editMode}
              isDragTarget={dropTargetIndex === index}
              onHide={hideWidget}
              onDragStart={handleDragStart}
              onDragOver={handleDragOver}
              onDrop={handleDrop}
              onDragEnd={handleDragEnd}
            >
              {renderer(widgetDataProps)}
            </WidgetWrapper>
          );
        })}
      </div>

      {/* Hidden widgets tray — only visible in edit mode */}
      {editMode && hiddenWidgets.length > 0 && (
        <div
          className="border border-dashed border-white/[0.08] rounded-xl p-4"
          aria-label="Hidden widgets"
        >
          <p className="text-xs font-display font-semibold text-txt-tertiary uppercase tracking-[0.15em] mb-3">
            Hidden
          </p>
          <div className="space-y-2">
            {hiddenWidgets.map((id) => (
              <div
                key={id}
                className="flex items-center justify-between gap-3 px-3 py-2 rounded-lg bg-bg-elevated/40"
              >
                <span className="text-sm text-txt-secondary font-display">
                  {WIDGET_LABELS[id]}
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => showWidget(id)}
                  aria-label={`Add ${WIDGET_LABELS[id]} to dashboard`}
                >
                  Add to dashboard
                </Button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Mobile customize dialog */}
      <DashboardCustomizeDialog
        open={mobileDialogOpen}
        onClose={() => setMobileDialogOpen(false)}
        layout={layout}
        showWidget={showWidget}
        hideWidget={hideWidget}
        moveWidgetByDelta={moveWidgetByDelta}
      />
    </div>
  );
}

export default Dashboard;
