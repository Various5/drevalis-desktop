import { Eye, EyeOff, ChevronUp, ChevronDown } from 'lucide-react';
import { Dialog, DialogFooter } from '@/components/ui/Dialog';
import { Button } from '@/components/ui/Button';
import { ALL_WIDGET_IDS, WIDGET_LABELS, type WidgetId } from './types';
import type { DashboardLayoutActions } from './useDashboardLayout';

// =============================================================================
// DashboardCustomizeDialog — mobile-only customization UI.
//
// Shows show/hide toggles + up/down arrows. Opened via the Customize button
// below the md breakpoint. On md+ the user drags widgets directly.
// =============================================================================

interface DashboardCustomizeDialogProps {
  open: boolean;
  onClose: () => void;
  layout: DashboardLayoutActions['layout'];
  showWidget: DashboardLayoutActions['showWidget'];
  hideWidget: DashboardLayoutActions['hideWidget'];
  moveWidgetByDelta: DashboardLayoutActions['moveWidgetByDelta'];
}

export function DashboardCustomizeDialog({
  open,
  onClose,
  layout,
  showWidget,
  hideWidget,
  moveWidgetByDelta,
}: DashboardCustomizeDialogProps) {
  const visibleSet = new Set(layout.widgets);

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Customize Dashboard"
      description="Choose which widgets to show and their order."
      maxWidth="sm"
    >
      <div className="space-y-1 py-2">
        {ALL_WIDGET_IDS.map((id: WidgetId) => {
          const isVisible = visibleSet.has(id);
          const idx = layout.widgets.indexOf(id);
          const canMoveUp = isVisible && idx > 0;
          const canMoveDown = isVisible && idx < layout.widgets.length - 1;

          return (
            <div
              key={id}
              className="flex items-center gap-2 p-2 rounded-lg hover:bg-bg-hover/40 transition-colors"
            >
              {/* Visibility toggle */}
              <button
                type="button"
                onClick={() =>
                  isVisible ? hideWidget(id) : showWidget(id)
                }
                className={[
                  'p-1.5 rounded transition-colors',
                  isVisible
                    ? 'text-accent hover:text-accent/80 hover:bg-accent/10'
                    : 'text-txt-tertiary hover:text-txt-primary hover:bg-bg-hover/60',
                ].join(' ')}
                aria-label={isVisible ? `Hide ${WIDGET_LABELS[id]}` : `Show ${WIDGET_LABELS[id]}`}
                aria-pressed={isVisible}
              >
                {isVisible ? <Eye size={14} /> : <EyeOff size={14} />}
              </button>

              {/* Label */}
              <span
                className={[
                  'flex-1 text-sm font-display',
                  isVisible ? 'text-txt-primary' : 'text-txt-tertiary',
                ].join(' ')}
              >
                {WIDGET_LABELS[id]}
              </span>

              {/* Up / Down arrows — only meaningful when visible */}
              {isVisible && (
                <div className="flex gap-1">
                  <button
                    type="button"
                    onClick={() => moveWidgetByDelta(id, -1)}
                    disabled={!canMoveUp}
                    className="p-1 rounded text-txt-tertiary hover:text-txt-primary hover:bg-bg-hover/60 disabled:opacity-30 disabled:pointer-events-none transition-colors"
                    aria-label={`Move ${WIDGET_LABELS[id]} up`}
                  >
                    <ChevronUp size={14} />
                  </button>
                  <button
                    type="button"
                    onClick={() => moveWidgetByDelta(id, 1)}
                    disabled={!canMoveDown}
                    className="p-1 rounded text-txt-tertiary hover:text-txt-primary hover:bg-bg-hover/60 disabled:opacity-30 disabled:pointer-events-none transition-colors"
                    aria-label={`Move ${WIDGET_LABELS[id]} down`}
                  >
                    <ChevronDown size={14} />
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </div>

      <DialogFooter>
        <Button variant="primary" size="sm" onClick={onClose}>
          Done
        </Button>
      </DialogFooter>
    </Dialog>
  );
}
