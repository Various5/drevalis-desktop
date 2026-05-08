import { useCallback, useEffect, useState } from 'react';
import {
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Info,
  Sparkles,
  RefreshCw,
} from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { Dialog, DialogFooter } from '@/components/ui/Dialog';
import { Spinner } from '@/components/ui/Spinner';
import { useToast } from '@/components/ui/Toast';
import { episodes as episodesApi, formatError } from '@/lib/api';

interface Check {
  id: string;
  severity: 'pass' | 'warn' | 'fail' | 'info';
  title: string;
  message: string;
  suggestion: string | null;
}

interface PreflightResult {
  score: number;
  grade: string;
  blocking: boolean;
  checks: Check[];
}

interface Variants {
  titles: string[];
  thumbnail_prompts: string[];
  descriptions: string[];
}

interface Props {
  episodeId: string;
  onClose: () => void;
  onConfirm: () => void;
}

export function SEOPreflightDialog({ episodeId, onClose, onConfirm }: Props) {
  const { toast } = useToast();
  const [result, setResult] = useState<PreflightResult | null>(null);
  const [variants, setVariants] = useState<Variants | null>(null);
  const [loading, setLoading] = useState(true);
  const [variantsLoading, setVariantsLoading] = useState(false);

  const runPreflight = useCallback(async () => {
    setLoading(true);
    try {
      const r = await episodesApi.seoPreflight(episodeId);
      setResult(r);
    } catch (err) {
      toast.error('Pre-flight failed', { description: formatError(err) });
    } finally {
      setLoading(false);
    }
  }, [episodeId, toast]);

  useEffect(() => {
    void runPreflight();
  }, [runPreflight]);

  const fetchVariants = async () => {
    setVariantsLoading(true);
    try {
      const v = await episodesApi.seoVariants(episodeId);
      setVariants(v);
    } catch (err) {
      toast.error('Couldn\'t get variants', { description: formatError(err) });
    } finally {
      setVariantsLoading(false);
    }
  };

  const SeverityIcon = ({ severity }: { severity: Check['severity'] }) => {
    const common = 'w-4 h-4 shrink-0';
    if (severity === 'pass') return <CheckCircle2 className={`${common} text-success`} />;
    if (severity === 'warn') return <AlertTriangle className={`${common} text-warning`} />;
    if (severity === 'fail') return <XCircle className={`${common} text-error`} />;
    return <Info className={`${common} text-txt-muted`} />;
  };

  const gradeClass =
    result?.grade === 'A'
      ? 'text-success bg-success/10 border-success/30'
      : result?.grade === 'B'
      ? 'text-accent bg-accent/10 border-accent/30'
      : result?.grade === 'C'
      ? 'text-warning bg-warning/10 border-warning/30'
      : 'text-error bg-error/10 border-error/30';

  return (
    <Dialog open onClose={onClose} title="Pre-upload SEO check" maxWidth="xl">
      {loading ? (
        <div className="py-10 flex justify-center">
          <Spinner size="lg" />
        </div>
      ) : !result ? (
        <div className="py-10 text-center text-sm text-txt-muted">
          Couldn't run pre-flight.
        </div>
      ) : (
        <div className="space-y-5">
          {/* Score card */}
          <Card className="p-5">
            <div className="flex items-center gap-4">
              <div
                className={`w-16 h-16 rounded-full flex items-center justify-center text-2xl font-bold border ${gradeClass}`}
              >
                {result.grade}
              </div>
              <div className="flex-1">
                <div className="text-2xl font-semibold">{result.score}/100</div>
                <div className="text-xs text-txt-muted">
                  {result.blocking ? (
                    <span className="text-error">
                      Blocking issues found — fix before uploading.
                    </span>
                  ) : (
                    <span>No blockers. Passing warnings is optional.</span>
                  )}
                </div>
              </div>
              <Button variant="ghost" size="sm" onClick={() => void runPreflight()}>
                <RefreshCw className="w-3.5 h-3.5 mr-1" />
                Re-check
              </Button>
            </div>
          </Card>

          {/* Checks */}
          <div className="space-y-2 max-h-64 overflow-y-auto">
            {result.checks.map((c) => (
              <div
                key={c.id}
                className="flex gap-3 p-3 rounded border border-white/[0.06] bg-bg-surface"
              >
                <SeverityIcon severity={c.severity} />
                <div className="flex-1">
                  <div className="text-sm font-medium">{c.title}</div>
                  <div className="text-xs text-txt-secondary">{c.message}</div>
                  {c.suggestion && (
                    <div className="text-xs text-accent mt-1">→ {c.suggestion}</div>
                  )}
                </div>
              </div>
            ))}
          </div>

          {/* LLM variants */}
          <div className="border-t border-white/[0.06] pt-4">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <Sparkles size={14} className="text-accent" />
                <span className="text-sm font-medium">AI variants</span>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => void fetchVariants()}
                disabled={variantsLoading}
              >
                {variantsLoading
                  ? 'Loading…'
                  : variants
                  ? 'Regenerate'
                  : 'Get title & thumbnail alternatives'}
              </Button>
            </div>

            {variants && (
              <div className="space-y-3">
                {variants.titles.length > 0 && (
                  <div>
                    <div className="text-[11px] uppercase tracking-wider text-txt-muted mb-1">
                      Titles
                    </div>
                    <ul className="space-y-1 text-sm text-txt-secondary">
                      {variants.titles.map((t, i) => (
                        <li
                          key={i}
                          className="px-2 py-1 rounded bg-bg-elevated hover:bg-bg-hover cursor-text"
                        >
                          {t}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {variants.thumbnail_prompts.length > 0 && (
                  <div>
                    <div className="text-[11px] uppercase tracking-wider text-txt-muted mb-1">
                      Thumbnail prompts
                    </div>
                    <ul className="space-y-1 text-xs text-txt-muted">
                      {variants.thumbnail_prompts.map((t, i) => (
                        <li key={i} className="px-2 py-1 rounded bg-bg-elevated">
                          {t}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      <DialogFooter>
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button
          variant={result?.blocking ? 'ghost' : 'primary'}
          onClick={onConfirm}
          disabled={loading}
        >
          {result?.blocking ? 'Upload anyway' : 'Upload'}
        </Button>
      </DialogFooter>
    </Dialog>
  );
}
