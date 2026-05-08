import { Lock, Sparkles } from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { ApiError } from '@/lib/api';

// ---------------------------------------------------------------------------
// Plan-aware placeholder for tier-gated features
// ---------------------------------------------------------------------------
//
// The backend returns ``402 feature_not_in_tier`` with a body shaped
// roughly:
//
//   { error: 'feature_not_in_tier', feature: 'seo_preflight',
//     tier: 'studio', current_tier: 'creator' }
//
// Pages consuming gated APIs should pass the caught ``ApiError`` to
// ``<TierGatePlaceholder error={err} />`` instead of silently
// suppressing the 402 — the user otherwise stares at a blank panel
// without knowing the feature exists.
//
// The component renders nothing for non-402 errors so callers can do
// ``{q.error && <TierGatePlaceholder error={q.error} />}`` without
// branching.

interface TierGateDetail {
  error?: string;
  feature?: string;
  tier?: string;
  current_tier?: string;
}

interface TierGatePlaceholderProps {
  error: unknown;
  /** Override the feature label (when the feature name from the error
   * isn't user-friendly). */
  featureLabel?: string;
  /** Optional CTA — defaults to a link to the License section in
   * Settings. */
  onUpgrade?: () => void;
}

function isTierGateError(error: unknown): error is ApiError & { detailRaw: TierGateDetail } {
  if (!(error instanceof ApiError)) return false;
  if (error.status !== 402) return false;
  const raw = error.detailRaw;
  return Boolean(raw && typeof raw === 'object' && 'feature' in raw);
}

export function TierGatePlaceholder({
  error,
  featureLabel,
  onUpgrade,
}: TierGatePlaceholderProps) {
  if (!isTierGateError(error)) return null;

  const detail = error.detailRaw;
  const tier = detail.tier ?? 'higher';
  const currentTier = detail.current_tier ?? 'your current';
  const feature = featureLabel ?? detail.feature ?? 'this feature';

  const handleUpgrade = onUpgrade ?? (() => {
    window.location.assign('/settings?section=license');
  });

  return (
    <Card padding="lg" className="border-accent/30 bg-accent/[0.04]">
      <div className="flex items-start gap-4">
        <div className="shrink-0 w-10 h-10 rounded-full bg-accent/15 flex items-center justify-center text-accent">
          <Lock size={18} aria-hidden="true" />
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-display font-semibold text-txt-primary capitalize">
            {String(feature).replace(/_/g, ' ')}
          </h3>
          <p className="mt-1 text-xs text-txt-secondary leading-relaxed">
            Available on the <span className="text-accent font-medium capitalize">{tier}</span> tier.
            You&rsquo;re currently on <span className="text-txt-primary font-medium capitalize">{currentTier}</span>.
          </p>
          <div className="mt-3">
            <Button variant="primary" size="sm" onClick={handleUpgrade}>
              <Sparkles size={14} />
              Upgrade
            </Button>
          </div>
        </div>
      </div>
    </Card>
  );
}

export { isTierGateError };
