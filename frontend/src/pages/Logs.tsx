import { useState, useEffect, useCallback } from 'react';
import { Terminal, RefreshCw, CheckCircle2, XCircle, Clock, AlertTriangle, ChevronDown, ChevronRight } from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Spinner } from '@/components/ui/Spinner';
import { Badge } from '@/components/ui/Badge';
import { EmptyState } from '@/components/ui/EmptyState';
import { PageHeader } from '@/components/ui/PageHeader';
import { StatCard } from '@/components/ui/StatCard';
import { metricsApi, eventsApi } from '@/lib/api';
import type { AppLogEvent, AppEventLevel } from '@/lib/api';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PipelineEvent {
  step: string;
  duration_seconds: number;
  success: boolean;
  episode_id: string;
  timestamp: string;
}

// ---------------------------------------------------------------------------
// Polling interval (ms)
// ---------------------------------------------------------------------------

const POLL_INTERVAL = 5000;

// ---------------------------------------------------------------------------
// Level badge colours (warning=yellow, error=red, critical=darker red)
// ---------------------------------------------------------------------------

function LevelBadge({ level }: { level: AppEventLevel }) {
  // Maps directly to the semantic Badge variants already in the design system.
  const variant = level === 'critical' ? 'error' : level; // warning | error
  const label = level.toUpperCase();

  // For critical we want a slightly different visual weight — add a darker
  // ring using a className override since the design system doesn't have a
  // dedicated "critical" variant.
  const extra = level === 'critical' ? 'ring-1 ring-red-700/60' : '';

  return (
    <Badge variant={variant} className={extra}>
      {label}
    </Badge>
  );
}

// ---------------------------------------------------------------------------
// Expandable context blob
// ---------------------------------------------------------------------------

function ContextBlob({ context }: { context: Record<string, unknown> }) {
  const [open, setOpen] = useState(false);
  const keys = Object.keys(context);

  if (keys.length === 0) return null;

  return (
    <div className="mt-1">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 text-[10px] text-txt-tertiary hover:text-txt-secondary transition-colors"
      >
        {open ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
        {open ? 'hide context' : `${keys.length} field${keys.length === 1 ? '' : 's'}`}
      </button>

      {open && (
        <pre className="mt-1 p-2 rounded bg-bg-secondary text-[10px] text-txt-secondary overflow-x-auto whitespace-pre-wrap break-all">
          {JSON.stringify(context, null, 2)}
        </pre>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// App Events section
// ---------------------------------------------------------------------------

const LEVEL_OPTIONS: { value: AppEventLevel; label: string }[] = [
  { value: 'warning', label: 'Warning+' },
  { value: 'error', label: 'Error+' },
  { value: 'critical', label: 'Critical only' },
];

function AppEventsSection({ autoRefresh }: { autoRefresh: boolean }) {
  const [appEvents, setAppEvents] = useState<AppLogEvent[]>([]);
  const [minLevel, setMinLevel] = useState<AppEventLevel>('warning');
  const [loading, setLoading] = useState(true);
  // null = not configured (empty list from server), false = fetch failed
  const [available, setAvailable] = useState<boolean | null>(null);

  const fetchAppEvents = useCallback(async () => {
    try {
      const data = await eventsApi.list(200, minLevel);
      setAppEvents(data.events);
      setAvailable(true);
    } catch {
      // 401/403 = no team mode or not owner — treat as not available.
      // Other errors — keep last data, don't flash an error state.
      setAvailable(false);
    }
  }, [minLevel]);

  useEffect(() => {
    setLoading(true);
    fetchAppEvents().finally(() => setLoading(false));
  }, [fetchAppEvents]);

  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(() => void fetchAppEvents(), POLL_INTERVAL);
    return () => clearInterval(interval);
  }, [autoRefresh, fetchAppEvents]);

  // ── Render ──────────────────────────────────────────────────────────

  return (
    <Card padding="none" className="mb-6">
      <div className="p-4 border-b border-border flex items-center justify-between">
        <div className="flex items-center gap-2">
          <AlertTriangle size={14} className="text-warning" />
          <span className="text-sm font-medium text-txt-primary">App events</span>
          {available && (
            <Badge variant="neutral">{appEvents.length}</Badge>
          )}
        </div>

        {/* Severity filter */}
        <select
          value={minLevel}
          onChange={(e) => setMinLevel(e.target.value as AppEventLevel)}
          className="text-xs bg-bg-secondary text-txt-secondary border border-border rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-accent"
          aria-label="Minimum severity"
        >
          {LEVEL_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      <div className="max-h-[50vh] overflow-y-auto p-4 scrollbar-thin">
        {loading ? (
          <div className="flex justify-center py-6">
            <Spinner size="sm" />
          </div>
        ) : available === false ? (
          <p className="text-xs text-txt-tertiary text-center py-4">
            App events require owner access (team mode) or{' '}
            <code className="font-mono">LOG_FILE</code> is not configured.
          </p>
        ) : appEvents.length === 0 ? (
          <EmptyState
            icon={AlertTriangle}
            title="No events recorded"
            description="Warning/error events from the structured log will appear here."
          />
        ) : (
          <div className="space-y-3">
            {appEvents.map((ev, i) => (
              <div
                key={i}
                className="py-2 border-b border-border/20 last:border-0"
              >
                <div className="flex items-start gap-2 flex-wrap">
                  {/* Timestamp */}
                  <span className="text-[11px] text-txt-tertiary font-mono shrink-0 mt-0.5">
                    {new Date(ev.timestamp).toLocaleString()}
                  </span>

                  {/* Level badge */}
                  <LevelBadge level={ev.level} />

                  {/* Logger (muted, small) */}
                  <span className="text-[10px] text-txt-tertiary font-mono mt-0.5 shrink-0">
                    {ev.logger}
                  </span>
                </div>

                {/* Event name (semibold) */}
                <p className="mt-1 text-xs font-semibold text-txt-primary font-mono">
                  {ev.event}
                </p>

                {/* Expandable context */}
                <ContextBlob context={ev.context} />
              </div>
            ))}
          </div>
        )}
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Logs Page
// ---------------------------------------------------------------------------

function Logs() {
  const [events, setEvents] = useState<PipelineEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [autoRefresh, setAutoRefresh] = useState(true);

  const fetchEvents = useCallback(async () => {
    try {
      const data = await metricsApi.events(200);
      setEvents(data);
    } catch {
      // ignore
    }
  }, []);

  // Initial load
  useEffect(() => {
    fetchEvents().finally(() => setLoading(false));
  }, [fetchEvents]);

  // Auto-refresh polling
  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(fetchEvents, POLL_INTERVAL);
    return () => clearInterval(interval);
  }, [autoRefresh, fetchEvents]);

  // ── Helpers ─────────────────────────────────────────────────────────

  const getStepColor = (step: string) => {
    const colors: Record<string, string> = {
      script: 'text-blue-400',
      voice: 'text-purple-400',
      scenes: 'text-green-400',
      captions: 'text-yellow-400',
      assembly: 'text-orange-400',
      thumbnail: 'text-pink-400',
    };
    return colors[step] || 'text-accent';
  };

  // ── Render ──────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <Spinner size="lg" />
      </div>
    );
  }

  return (
    <div>
      {/* Banner already shows "Event Log"; subtitle + actions only. */}
      <PageHeader
        subtitle="Recent pipeline execution events."
        actions={
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
                className="w-4 h-4 rounded accent-accent"
              />
              <span className="text-sm text-txt-secondary">Auto-refresh</span>
            </label>
            <Button variant="ghost" size="sm" onClick={() => void fetchEvents()}>
              <RefreshCw size={14} />
              Refresh
            </Button>
          </div>
        }
      />

      {/* ── App events (structured log file) ─────────────────────────── */}
      <AppEventsSection autoRefresh={autoRefresh} />

      {/* Stats summary — uses the shared StatCard so the visual
          treatment matches the Dashboard tiles. */}
      {events.length > 0 && (() => {
        const successCount = events.filter((e) => e.success).length;
        const failedCount = events.filter((e) => !e.success).length;
        const avgDuration =
          events.reduce((sum, e) => sum + (e.duration_seconds || 0), 0) /
          events.length;
        return (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <StatCard
              label="Total Events"
              value={events.length}
              icon={<Terminal size={20} />}
              color="#EDEDEF"
            />
            <StatCard
              label="Successful"
              value={successCount}
              icon={<CheckCircle2 size={20} />}
              color="#34D399"
            />
            <StatCard
              label="Failed"
              value={failedCount}
              icon={<XCircle size={20} />}
              color="#F87171"
            />
            <StatCard
              label="Avg Duration"
              value={`${avgDuration.toFixed(1)}s`}
              icon={<Clock size={20} />}
              color="#00D4AA"
            />
          </div>
        );
      })()}

      {/* Pipeline events */}
      <Card padding="none">
        <div className="p-4 border-b border-border flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Terminal size={14} className="text-txt-tertiary" />
            <span className="text-sm font-medium text-txt-primary">Pipeline events</span>
            <Badge variant="neutral">{events.length}</Badge>
          </div>
        </div>

        <div className="font-mono text-xs max-h-[65vh] overflow-y-auto p-4 scrollbar-thin">
          {events.length === 0 ? (
            <EmptyState
              icon={Terminal}
              title="No pipeline events recorded yet"
              description="Events appear here as episodes are generated."
            />
          ) : (
            <div className="space-y-0">
              {events.map((e, i) => (
                <div
                  key={i}
                  className={[
                    'py-1.5 border-b border-border/20 flex items-center gap-3',
                    e.success ? 'text-txt-secondary' : 'text-error',
                  ].join(' ')}
                >
                  <span className="text-txt-tertiary w-20 shrink-0">
                    {new Date(e.timestamp).toLocaleTimeString()}
                  </span>
                  <span className={e.success ? 'text-success' : 'text-error'}>
                    {e.success ? '✓' : '✗'}
                  </span>
                  <span className={`w-20 shrink-0 ${getStepColor(e.step)}`}>{e.step}</span>
                  <span className="text-txt-tertiary w-16 shrink-0 text-right">
                    {e.duration_seconds?.toFixed(1)}s
                  </span>
                  <span className="text-txt-tertiary">
                    {e.episode_id?.slice(0, 8)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}

export default Logs;
