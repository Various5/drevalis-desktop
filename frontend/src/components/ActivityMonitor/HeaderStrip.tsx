/**
 * HeaderStrip — always-visible 32 px band at the top of the dock.
 *
 * Layout:
 *   [worker-dot  Worker: Active/Down  ·  N/M slots  ·  N queued]   [priority <select>]
 *
 * The aria-live region on the worker status text is preserved from the
 * Phase 5 accessibility pass (R3).
 */

import { RefreshCw } from 'lucide-react';
import { LiveStatus } from '@/components/ui/LiveStatus';
import { Spinner } from '@/components/ui/Spinner';
import { Button } from '@/components/ui/Button';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type PriorityMode = 'shorts_first' | 'longform_first' | 'fifo';

interface QueueStatus {
  active: number;
  queued: number;
  max_concurrent: number;
}

interface WorkerHealth {
  alive: boolean;
}

interface HeaderStripProps {
  workerHealth: WorkerHealth | null;
  wsConnected: boolean;
  queueStatus: QueueStatus | null;
  priority: PriorityMode;
  restartingWorker: boolean;
  onRestartWorker: () => void;
  onPriorityChange: (next: PriorityMode) => void;
  /** Whether the dock is expanded (controls chevron direction on click) */
  expanded: boolean;
  onToggleExpanded: () => void;
}

// ---------------------------------------------------------------------------
// Priority options
// ---------------------------------------------------------------------------

const PRIORITY_OPTIONS: { value: PriorityMode; label: string }[] = [
  { value: 'shorts_first', label: 'Shorts First' },
  { value: 'longform_first', label: 'Longform First' },
  { value: 'fifo', label: 'FIFO' },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function HeaderStrip({
  workerHealth,
  wsConnected,
  queueStatus,
  priority,
  restartingWorker,
  onRestartWorker,
  onPriorityChange,
  expanded,
  onToggleExpanded,
}: HeaderStripProps) {
  const workerAlive = workerHealth?.alive ?? null;

  const workerDotClass = [
    'w-2 h-2 rounded-full flex-shrink-0',
    workerAlive === null
      ? 'bg-txt-tertiary'
      : workerAlive
        ? 'bg-green-500'
        : 'bg-red-500 animate-pulse',
  ].join(' ');

  const workerLabelClass = [
    'text-xs font-medium',
    workerAlive === null
      ? 'text-txt-tertiary'
      : workerAlive
        ? 'text-green-400'
        : 'text-red-400',
  ].join(' ');

  return (
    <div
      className="flex items-center justify-between px-3 h-8 gap-3 select-none"
      data-testid="activity-header-strip"
    >
      {/* ── Left cluster: worker dot + status + slots + ws ──────────── */}
      <button
        className="flex items-center gap-2 min-w-0 cursor-pointer hover:opacity-80 transition-opacity focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2 rounded-sm"
        onClick={onToggleExpanded}
        aria-expanded={expanded}
        aria-label={expanded ? 'Collapse activity monitor' : 'Expand activity monitor'}
      >
        {/* Worker dot */}
        <span className={workerDotClass} aria-hidden="true" />

        {/* Worker label — aria-live preserved from Phase 5 */}
        <span
          className={workerLabelClass}
          role="status"
          aria-live="polite"
        >
          Worker:{' '}
          {workerAlive === null ? 'Unknown' : workerAlive ? 'Active' : 'Down'}
        </span>

        {/* Slots + queued */}
        {queueStatus && (
          <span className="text-[10px] text-txt-tertiary whitespace-nowrap">
            {'·'} {queueStatus.active}/{queueStatus.max_concurrent}
            {queueStatus.queued > 0 && ` · ${queueStatus.queued} queued`}
          </span>
        )}

        {/* WS health indicator — compact */}
        <LiveStatus connected={wsConnected} className="text-[9px] h-4 px-1.5" />
      </button>

      {/* ── Right cluster: restart + priority ───────────────────────── */}
      <div className="flex items-center gap-2 flex-shrink-0">
        {/* Restart worker — visible only when worker is down */}
        {workerAlive === false && (
          <Button
            variant="ghost"
            size="sm"
            className="text-[10px] h-6 px-2 text-amber-400 hover:text-amber-300"
            onClick={onRestartWorker}
            disabled={restartingWorker}
            aria-label="Restart worker process"
          >
            {restartingWorker ? <Spinner size="sm" /> : <RefreshCw size={10} />}
            Restart
          </Button>
        )}

        {/* Priority selector */}
        <select
          value={priority}
          onChange={(e) => onPriorityChange(e.target.value as PriorityMode)}
          className="h-7 px-2 pr-6 text-[10px] text-txt-secondary appearance-none bg-bg-elevated/60 border border-white/[0.06] rounded cursor-pointer hover:border-white/[0.1] focus-visible:outline-2 focus-visible:outline-accent transition-colors"
          aria-label="Queue priority mode"
        >
          {PRIORITY_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
