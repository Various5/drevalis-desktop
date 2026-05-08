/**
 * BulkActions strip — shown only when totalActive > 0 OR failedCount > 0.
 *
 * Single horizontal row:
 *   [Pause All]  [Cancel All]  [Retry Failed (N)]
 *
 * Each button is ghost, sm, icon-leading with a tooltip on hover.
 * On mobile (< md) the whole strip is hidden — the mobile pill navigates
 * to /jobs which has the same controls at a comfortable touch size.
 */

import { Pause, Square, RotateCcw, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Tooltip } from '@/components/ui/Tooltip';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface BulkActionsProps {
  totalActive: number;
  failedCount: number;
  onPauseAll: () => void;
  onCancelAll: () => void;
  onRetryFailed: () => void;
  onCleanup: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function BulkActions({
  totalActive,
  failedCount,
  onPauseAll,
  onCancelAll,
  onRetryFailed,
  onCleanup,
}: BulkActionsProps) {
  const isVisible = totalActive > 0 || failedCount > 0;

  if (!isVisible) return null;

  return (
    <div
      className="flex items-center gap-1 px-3 py-1.5 border-t border-white/[0.05]"
      data-testid="bulk-actions-strip"
    >
      <Tooltip content="Pause all running jobs" side="top">
        <Button
          variant="ghost"
          size="sm"
          className="text-[10px] h-6 px-2 text-amber-400 hover:text-amber-300 gap-1"
          onClick={onPauseAll}
          aria-label="Pause all running jobs"
        >
          <Pause size={11} aria-hidden="true" />
          Pause
        </Button>
      </Tooltip>

      {totalActive > 0 && (
        <Tooltip content="Cancel all running jobs" side="top">
          <Button
            variant="ghost"
            size="sm"
            className="text-[10px] h-6 px-2 text-red-400 hover:text-red-300 gap-1"
            onClick={onCancelAll}
            aria-label="Cancel all running jobs"
          >
            <Square size={11} aria-hidden="true" />
            Cancel
          </Button>
        </Tooltip>
      )}

      {failedCount > 0 && (
        <Tooltip content={`Retry ${failedCount} failed jobs`} side="top">
          <Button
            variant="ghost"
            size="sm"
            className="text-[10px] h-6 px-2 text-green-400 hover:text-green-300 gap-1"
            onClick={onRetryFailed}
            aria-label={`Retry ${failedCount} failed jobs`}
          >
            <RotateCcw size={11} aria-hidden="true" />
            Retry ({failedCount})
          </Button>
        </Tooltip>
      )}

      {/* Cleanup — always visible when strip is shown */}
      <Tooltip content="Clean up stale job records" side="top">
        <Button
          variant="ghost"
          size="sm"
          className="text-[10px] h-6 px-2 text-txt-tertiary hover:text-txt-secondary gap-1 ml-auto"
          onClick={onCleanup}
          aria-label="Clean up stale job records"
        >
          <Trash2 size={11} aria-hidden="true" />
          Cleanup
        </Button>
      </Tooltip>
    </div>
  );
}
