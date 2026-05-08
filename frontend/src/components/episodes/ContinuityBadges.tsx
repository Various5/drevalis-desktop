import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, Info, XCircle, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { episodes as episodesApi, formatError } from '@/lib/api';
import { useToast } from '@/components/ui/Toast';

interface Issue {
  from_scene: number;
  to_scene: number;
  severity: 'info' | 'warn' | 'fail';
  issue: string;
  suggestion: string;
}

/**
 * Pill strip + expandable issue list rendered above the scene grid.
 *
 * On mount fetches continuity results once; operator can re-run via
 * the "Re-check" button. Each issue renders the two scene numbers
 * it bridges, a severity-colored dot, and the suggestion on expand.
 */
export function ContinuityBadges({ episodeId }: { episodeId: string }) {
  const { toast } = useToast();
  const [issues, setIssues] = useState<Issue[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const fetch = useCallback(async () => {
    setLoading(true);
    try {
      const r = await episodesApi.continuity(episodeId);
      setIssues(r.issues as Issue[]);
    } catch (err) {
      toast.error('Continuity check failed', { description: formatError(err) });
      setIssues([]);
    } finally {
      setLoading(false);
    }
  }, [episodeId, toast]);

  useEffect(() => {
    void fetch();
  }, [fetch]);

  if (loading && issues === null) {
    return (
      <div className="text-[11px] text-txt-muted italic mb-3">
        Running continuity check…
      </div>
    );
  }
  if (issues === null) return null;

  if (issues.length === 0) {
    return (
      <div className="flex items-center gap-2 mb-3 text-xs">
        <span className="inline-flex w-2 h-2 rounded-full bg-success" />
        <span className="text-txt-muted">No continuity issues flagged.</span>
        <Button variant="ghost" size="sm" onClick={() => void fetch()} className="ml-auto">
          <RefreshCw className="w-3 h-3" />
        </Button>
      </div>
    );
  }

  const counts = issues.reduce<Record<string, number>>(
    (acc, i) => ({ ...acc, [i.severity]: (acc[i.severity] || 0) + 1 }),
    {},
  );

  return (
    <div className="mb-3 rounded border border-white/[0.06] bg-bg-surface">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center gap-2 w-full px-3 py-2 text-left hover:bg-white/[0.02] rounded-t"
      >
        <AlertTriangle className="w-4 h-4 text-warning" />
        <span className="text-xs font-medium">
          {issues.length} continuity {issues.length === 1 ? 'issue' : 'issues'}
        </span>
        <div className="flex items-center gap-1 ml-2">
          {counts.fail ? (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-error/20 text-error">
              {counts.fail} fail
            </span>
          ) : null}
          {counts.warn ? (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-warning/20 text-warning">
              {counts.warn} warn
            </span>
          ) : null}
          {counts.info ? (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-bg-elevated text-txt-muted">
              {counts.info} info
            </span>
          ) : null}
        </div>
        <div className="flex-1" />
        <span className="text-xs text-txt-muted">{expanded ? 'Hide' : 'Show'}</span>
      </button>
      {expanded && (
        <div className="border-t border-white/[0.04] divide-y divide-white/[0.04]">
          {issues.map((i, idx) => (
            <div key={idx} className="px-3 py-2 text-xs flex gap-3">
              <SeverityIcon s={i.severity} />
              <div className="flex-1">
                <div className="font-mono text-[10px] text-txt-muted">
                  scene {i.from_scene} → scene {i.to_scene}
                </div>
                <div className="text-txt-primary">{i.issue}</div>
                {i.suggestion && (
                  <div className="text-txt-muted mt-0.5">→ {i.suggestion}</div>
                )}
              </div>
            </div>
          ))}
          <div className="px-3 py-2 text-right">
            <Button variant="ghost" size="sm" onClick={() => void fetch()}>
              <RefreshCw className="w-3 h-3 mr-1" />
              Re-check
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function SeverityIcon({ s }: { s: Issue['severity'] }) {
  const cls = 'w-4 h-4 shrink-0 mt-0.5';
  if (s === 'fail') return <XCircle className={`${cls} text-error`} />;
  if (s === 'warn') return <AlertTriangle className={`${cls} text-warning`} />;
  return <Info className={`${cls} text-txt-muted`} />;
}

/**
 * Small dot between two scene cards (consumed by the scene grid) —
 * click to scroll to the full issue in the ContinuityBadges card
 * above.
 */
export function ContinuityDot({
  severity,
  title,
  onClick,
}: {
  severity: Issue['severity'];
  title: string;
  onClick?: () => void;
}) {
  const color =
    severity === 'fail'
      ? 'bg-error'
      : severity === 'warn'
      ? 'bg-warning'
      : 'bg-txt-muted';
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className={`w-2.5 h-2.5 rounded-full ${color} hover:scale-125 transition-transform`}
    />
  );
}
