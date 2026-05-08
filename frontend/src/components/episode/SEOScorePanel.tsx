import { useEffect, useState } from 'react';
import { CheckCircle2, AlertTriangle, XCircle, Info, RefreshCw } from 'lucide-react';
import { episodes, type SEOScore } from '@/lib/api';

interface Props {
  episodeId: string;
  /** Trigger a re-fetch when this changes (e.g. after script edits or SEO regen). */
  refreshKey?: number;
}

const GRADE_COLORS: Record<SEOScore['grade'], string> = {
  A: 'text-[var(--accent,#00E5B8)] border-[var(--accent,#00E5B8)]/40 bg-[var(--accent,#00E5B8)]/10',
  B: 'text-emerald-300 border-emerald-400/40 bg-emerald-400/10',
  C: 'text-amber-300 border-amber-400/40 bg-amber-400/10',
  D: 'text-rose-300 border-rose-400/40 bg-rose-400/10',
};

function SeverityIcon({ severity }: { severity: 'ok' | 'warn' | 'error' | 'info' }) {
  if (severity === 'ok') return <CheckCircle2 size={14} className="text-accent shrink-0" />;
  if (severity === 'warn') return <AlertTriangle size={14} className="text-amber-400 shrink-0" />;
  if (severity === 'error') return <XCircle size={14} className="text-rose-400 shrink-0" />;
  return <Info size={14} className="text-txt-muted shrink-0" />;
}

export function SEOScorePanel({ episodeId, refreshKey = 0 }: Props) {
  const [score, setScore] = useState<SEOScore | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr(null);
    episodes
      .seoScore(episodeId)
      .then((s) => {
        if (!cancelled) setScore(s);
      })
      .catch((e) => {
        if (!cancelled) setErr(e?.message || 'Could not load SEO score');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [episodeId, refreshKey]);

  if (loading) {
    return (
      <div className="rounded-lg border border-border bg-bg-elevated p-4 flex items-center gap-2 text-sm text-txt-muted">
        <RefreshCw size={14} className="animate-spin" />
        Scoring metadata…
      </div>
    );
  }

  if (err || !score) {
    return (
      <div className="rounded-lg border border-border bg-bg-elevated p-4 text-sm text-txt-muted">
        {err ?? 'SEO score unavailable.'}
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border bg-bg-elevated p-4">
      <div className="flex items-center gap-3 mb-3">
        <div
          className={`w-12 h-12 rounded-md border flex items-center justify-center font-display text-2xl font-bold ${GRADE_COLORS[score.grade]}`}
          title={`Score: ${score.overall_score} / 100`}
        >
          {score.grade}
        </div>
        <div className="min-w-0">
          <div className="text-sm font-semibold text-txt-primary">
            SEO score: {score.overall_score} / 100
          </div>
          <div className="text-xs text-txt-secondary truncate">{score.summary}</div>
        </div>
      </div>

      <div className="space-y-1.5">
        {score.checks.map((c) => (
          <div key={c.id} className="flex items-start gap-2 text-xs">
            <SeverityIcon severity={c.severity} />
            <div className="min-w-0 flex-1">
              <span
                className={
                  c.severity === 'error'
                    ? 'text-rose-200'
                    : c.severity === 'warn'
                      ? 'text-amber-200'
                      : c.severity === 'info'
                        ? 'text-txt-muted'
                        : 'text-txt-primary'
                }
              >
                <strong className="font-medium">{c.label}.</strong> {c.hint}
              </span>
            </div>
          </div>
        ))}
      </div>

      {!score.has_seo_metadata && (
        <p className="mt-3 text-[11px] text-txt-muted border-t border-border pt-3">
          Tip: click <strong>Generate SEO</strong> on this episode to replace these heuristics
          with LLM-optimised title, description, hashtags, and tags.
        </p>
      )}
    </div>
  );
}

export default SEOScorePanel;
