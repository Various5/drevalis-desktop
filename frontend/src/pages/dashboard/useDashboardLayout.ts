// =============================================================================
// useDashboardLayout — reads/writes the DashboardLayout preference.
//
// Falls back to DEFAULT_LAYOUT when:
//   - prefs haven't been written yet (undefined)
//   - version doesn't match (forward-compat for future schema bumps)
// =============================================================================

import { useCallback, useMemo } from 'react';
import { usePreferences } from '@/lib/usePreferences';
import {
  ALL_WIDGET_IDS,
  DEFAULT_LAYOUT,
  type DashboardLayout,
  type WidgetId,
} from './types';

function isValidLayout(raw: unknown): raw is DashboardLayout {
  if (!raw || typeof raw !== 'object') return false;
  const obj = raw as Record<string, unknown>;
  return (
    obj['version'] === 1 &&
    Array.isArray(obj['widgets']) &&
    Array.isArray(obj['hidden'])
  );
}

/** Repair a persisted layout to only reference known widget ids. */
function sanitize(layout: DashboardLayout): DashboardLayout {
  const known = new Set<string>(ALL_WIDGET_IDS);
  const widgets = layout.widgets.filter((id): id is WidgetId => known.has(id));
  const hidden = layout.hidden.filter((id): id is WidgetId => known.has(id));

  // Any known id that is neither in widgets nor hidden gets appended to
  // hidden so new widgets added in future versions don't disappear.
  const seen = new Set<string>([...widgets, ...hidden]);
  const newHidden: WidgetId[] = [...hidden];
  for (const id of ALL_WIDGET_IDS) {
    if (!seen.has(id)) newHidden.push(id);
  }

  return { version: 1, widgets, hidden: newHidden };
}

export interface DashboardLayoutActions {
  layout: DashboardLayout;
  isLoading: boolean;
  /** Move a widget before the widget at targetIndex in the visible list. */
  moveWidget: (fromIndex: number, toIndex: number) => void;
  /** Hide a visible widget (move from widgets → hidden). */
  hideWidget: (id: WidgetId) => void;
  /** Show a hidden widget (append to visible widgets). */
  showWidget: (id: WidgetId) => void;
  /** Move widget up/down within the visible list (for mobile). */
  moveWidgetByDelta: (id: WidgetId, delta: -1 | 1) => void;
}

export function useDashboardLayout(): DashboardLayoutActions {
  const { prefs, update, isLoading } = usePreferences<DashboardLayout>(
    'dashboard_layout',
  );

  const layout = useMemo<DashboardLayout>(() => {
    if (!isValidLayout(prefs)) return DEFAULT_LAYOUT;
    return sanitize(prefs);
  }, [prefs]);

  const persist = useCallback(
    (next: DashboardLayout) => {
      void update(next);
    },
    [update],
  );

  const moveWidget = useCallback(
    (fromIndex: number, toIndex: number) => {
      if (fromIndex === toIndex) return;
      const widgets = [...layout.widgets];
      const [moved] = widgets.splice(fromIndex, 1);
      if (!moved) return;
      widgets.splice(toIndex, 0, moved);
      persist({ ...layout, widgets });
    },
    [layout, persist],
  );

  const hideWidget = useCallback(
    (id: WidgetId) => {
      const widgets = layout.widgets.filter((w) => w !== id);
      const hidden = layout.hidden.includes(id)
        ? layout.hidden
        : [...layout.hidden, id];
      persist({ ...layout, widgets, hidden });
    },
    [layout, persist],
  );

  const showWidget = useCallback(
    (id: WidgetId) => {
      if (layout.widgets.includes(id)) return;
      const widgets = [...layout.widgets, id];
      const hidden = layout.hidden.filter((w) => w !== id);
      persist({ ...layout, widgets, hidden });
    },
    [layout, persist],
  );

  const moveWidgetByDelta = useCallback(
    (id: WidgetId, delta: -1 | 1) => {
      const idx = layout.widgets.indexOf(id);
      if (idx === -1) return;
      const next = idx + delta;
      if (next < 0 || next >= layout.widgets.length) return;
      moveWidget(idx, next);
    },
    [layout, moveWidget],
  );

  return { layout, isLoading, moveWidget, hideWidget, showWidget, moveWidgetByDelta };
}
