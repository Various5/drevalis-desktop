import { useEffect, useState } from 'react';
import { Gauge, Infinity as InfinityIcon } from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Spinner } from '@/components/ui/Spinner';
import { license as licenseApi } from '@/lib/api';

// ---------------------------------------------------------------------------
// QuotaUsageWidget — today's episode-generation usage vs daily cap
// ---------------------------------------------------------------------------
//
// Reads ``GET /api/v1/license/quota`` (cheap, Redis-backed). Renders a
// progress bar when the tier has a cap and the ∞ glyph for unlimited
// tiers. Refreshes on focus so a long-running generate visible in
// another tab updates this widget.

interface QuotaShape {
  used: number;
  limit: number | null;
}

export function QuotaUsageWidget() {
  const [data, setData] = useState<QuotaShape | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await licenseApi.quota();
        if (!cancelled) setData(res);
      } catch {
        if (!cancelled) setData({ used: 0, limit: 0 });
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
          Today&rsquo;s Generations
        </h2>
        <Gauge size={14} className="text-txt-tertiary" aria-hidden="true" />
      </div>
      {data === null ? (
        <div className="flex items-center justify-center py-6">
          <Spinner size="sm" />
        </div>
      ) : data.limit === null ? (
        <div className="flex items-baseline gap-2">
          <span className="text-2xl font-display font-bold text-txt-primary tabular-nums">
            {data.used}
          </span>
          <span className="text-sm text-txt-tertiary inline-flex items-center gap-1">
            of <InfinityIcon size={14} aria-label="unlimited" /> today
          </span>
        </div>
      ) : (
        <>
          <div className="flex items-baseline gap-2 mb-2">
            <span className="text-2xl font-display font-bold text-txt-primary tabular-nums">
              {data.used}
            </span>
            <span className="text-sm text-txt-tertiary tabular-nums">
              / {data.limit} today
            </span>
          </div>
          <div className="h-1.5 rounded-full bg-bg-elevated overflow-hidden">
            <div
              className={[
                'h-full transition-all duration-slow',
                data.used >= data.limit
                  ? 'bg-error'
                  : data.used / data.limit >= 0.8
                    ? 'bg-warning'
                    : 'bg-accent',
              ].join(' ')}
              style={{
                width: `${Math.min(100, (data.used / Math.max(1, data.limit)) * 100)}%`,
              }}
              role="progressbar"
              aria-valuenow={data.used}
              aria-valuemin={0}
              aria-valuemax={data.limit}
              aria-label="Daily generation quota"
            />
          </div>
        </>
      )}
    </Card>
  );
}
