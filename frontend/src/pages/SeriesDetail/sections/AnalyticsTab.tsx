import { ABTestsPanel } from '@/components/series/ABTestsPanel';

// ---------------------------------------------------------------------------
// AnalyticsTab
//
// A/B test results panel + future performance widgets for this series.
// Kept deliberately thin — the ABTestsPanel is self-contained and manages
// its own data fetching.
// ---------------------------------------------------------------------------

export interface AnalyticsTabProps {
  seriesId: string;
}

export function AnalyticsTab({ seriesId }: AnalyticsTabProps) {
  return (
    <div className="space-y-6">
      <ABTestsPanel seriesId={seriesId} />
    </div>
  );
}
