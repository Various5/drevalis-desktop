// =============================================================================
// Dashboard layout types — shared between the hook, the page, and tests.
// =============================================================================

export type WidgetId =
  | 'setup-checklist'
  | 'system-health'
  | 'stat-cards'
  | 'quick-actions'
  | 'recent-episodes'
  | 'activity-timeline'
  | 'active-jobs'
  | 'upcoming-posts'
  | 'top-series'
  | 'quota-usage';

export interface DashboardLayout {
  version: 1;
  /** Ordered list of widget ids that ARE rendered, top to bottom. */
  widgets: WidgetId[];
  /** Ids the user has hidden. */
  hidden: WidgetId[];
}

export const ALL_WIDGET_IDS: readonly WidgetId[] = [
  'setup-checklist',
  'system-health',
  'stat-cards',
  'quick-actions',
  'recent-episodes',
  'activity-timeline',
  'active-jobs',
  'upcoming-posts',
  'top-series',
  'quota-usage',
] as const;

export const WIDGET_LABELS: Record<WidgetId, string> = {
  'setup-checklist': 'Setup Checklist',
  'system-health': 'System Health',
  'stat-cards': 'Statistics',
  'quick-actions': 'Quick Actions',
  'recent-episodes': 'Recent Episodes',
  'activity-timeline': 'Activity Timeline',
  'active-jobs': 'Active Jobs',
  'upcoming-posts': 'Upcoming Posts',
  'top-series': 'Top Series',
  'quota-usage': 'Today’s Generations',
};

export const DEFAULT_LAYOUT: DashboardLayout = {
  version: 1,
  widgets: [
    'setup-checklist',
    'system-health',
    'stat-cards',
    'quick-actions',
    'recent-episodes',
    'activity-timeline',
  ],
  // Off by default so the existing dashboard still renders the same on
  // first paint. Users discover the new widgets via "Customize → Add".
  hidden: ['active-jobs', 'upcoming-posts', 'top-series', 'quota-usage'],
};
