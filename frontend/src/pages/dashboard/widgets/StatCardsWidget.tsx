import { Film, Zap, CheckCircle2, AlertTriangle } from 'lucide-react';
import { StatCard } from '@/components/ui/StatCard';

// ---------------------------------------------------------------------------
// StatCardsWidget — the 4-card stat row on the Dashboard
// ---------------------------------------------------------------------------

interface StatCardsWidgetProps {
  totalEpisodes: number;
  completedCount: number;
  failedCount: number;
  totalSeries: number;
}

export function StatCardsWidget({
  totalEpisodes,
  completedCount,
  failedCount,
  totalSeries,
}: StatCardsWidgetProps) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      <StatCard
        label="Total Episodes"
        value={totalEpisodes}
        icon={<Film size={20} />}
        color="#EDEDEF"
      />
      <StatCard
        label="Completed"
        value={completedCount}
        icon={<CheckCircle2 size={20} />}
        color="#34D399"
      />
      <StatCard
        label="Failed"
        value={failedCount}
        icon={<AlertTriangle size={20} />}
        color="#F87171"
      />
      <StatCard
        label="Total Series"
        value={totalSeries}
        icon={<Zap size={20} />}
        color="#00D4AA"
      />
    </div>
  );
}
