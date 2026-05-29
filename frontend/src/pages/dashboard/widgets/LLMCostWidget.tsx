import { useEffect, useState } from 'react';
import { DollarSign } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Card } from '@/components/ui/Card';
import { Spinner } from '@/components/ui/Spinner';

// ---------------------------------------------------------------------------
// LLMCostWidget — estimated LLM spend over the last 30 days.
// ---------------------------------------------------------------------------

interface CostSummary {
  window_days: number;
  tokens_prompt: number;
  tokens_completion: number;
  tokens_total: number;
  estimated_usd: number;
  rate_per_1k_prompt: number;
  rate_per_1k_completion: number;
}

function formatUsd(v: number): string {
  if (v < 0.01) return '< $0.01';
  if (v < 1) return `$${v.toFixed(3)}`;
  if (v < 100) return `$${v.toFixed(2)}`;
  return `$${Math.round(v).toLocaleString()}`;
}

function formatTokens(v: number): string {
  if (v < 1000) return String(v);
  if (v < 1_000_000) return `${(v / 1000).toFixed(1)}K`;
  return `${(v / 1_000_000).toFixed(2)}M`;
}

export function LLMCostWidget() {
  const { t } = useTranslation();
  const [data, setData] = useState<CostSummary | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await fetch('/api/v1/cost/summary?days=30', {
          credentials: 'include',
        });
        if (!res.ok) {
          if (!cancelled) setData(null);
          return;
        }
        const json = (await res.json()) as CostSummary;
        if (!cancelled) setData(json);
      } catch {
        if (!cancelled) setData(null);
      }
    };
    void load();
    const onFocus = () => void load();
    window.addEventListener('focus', onFocus);
    return () => {
      cancelled = true;
      window.removeEventListener('focus', onFocus);
    };
  }, []);

  return (
    <Card padding="md">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-xs font-display font-semibold text-txt-tertiary uppercase tracking-[0.15em]">
          {t('dashboard.widgets.llmCost.heading')}
        </h2>
        <DollarSign size={14} className="text-txt-tertiary" aria-hidden="true" />
      </div>
      {data === null ? (
        <div className="flex items-center justify-center py-6">
          <Spinner size="sm" />
        </div>
      ) : (
        <div className="space-y-2">
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-display font-bold text-txt-primary tabular-nums">
              {formatUsd(data.estimated_usd)}
            </span>
            <span className="text-xs text-txt-tertiary">{t('dashboard.widgets.llmCost.estimated')}</span>
          </div>
          <div className="text-xs text-txt-secondary tabular-nums">
            {t('dashboard.widgets.llmCost.inOutTokens', {
              in: formatTokens(data.tokens_prompt),
              out: formatTokens(data.tokens_completion),
            })}
          </div>
          <div className="text-[10px] text-txt-tertiary leading-tight">
            {t('dashboard.widgets.llmCost.rateLine', {
              prompt: data.rate_per_1k_prompt.toFixed(5),
              completion: data.rate_per_1k_completion.toFixed(5),
            })}
          </div>
        </div>
      )}
    </Card>
  );
}
