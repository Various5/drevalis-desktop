import { useNavigate } from 'react-router-dom';
import { Plus, TrendingUp, CalendarDays, Clapperboard } from 'lucide-react';
import { QuickActionTile } from '@/components/ui/QuickActionTile';

// ---------------------------------------------------------------------------
// QuickActionsWidget — 4-tile quick-action grid on the Dashboard
// ---------------------------------------------------------------------------

interface QuickActionsWidgetProps {
  seriesList: { id: string }[];
}

export function QuickActionsWidget({ seriesList }: QuickActionsWidgetProps) {
  const navigate = useNavigate();

  return (
    <div>
      <h2 className="text-xs font-display font-semibold text-txt-tertiary uppercase tracking-[0.15em] mb-3">
        Quick Actions
      </h2>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <QuickActionTile
          icon={<Plus size={18} />}
          label="New Series"
          hint="Create a new series"
          accent="accent"
          onClick={() => navigate('/series')}
          ariaLabel="Create New Series"
        />
        <QuickActionTile
          icon={<TrendingUp size={18} />}
          label="Trending Topics"
          hint="Discover viral ideas"
          accent="success"
          onClick={() => {
            const firstSeries = seriesList[0];
            if (firstSeries) {
              navigate(`/series/${firstSeries.id}?tab=trending`);
            } else {
              navigate('/series');
            }
          }}
          ariaLabel="Generate Trending Topics"
        />
        <QuickActionTile
          icon={<CalendarDays size={18} />}
          label="Calendar"
          hint="Schedule content"
          accent="info"
          onClick={() => navigate('/calendar')}
          ariaLabel="View Content Calendar"
        />
        <QuickActionTile
          icon={<Clapperboard size={18} />}
          label="New from video"
          hint="Upload → pick clip → edit"
          accent="warning"
          onClick={() => navigate('/assets?ingest=1')}
          ariaLabel="Create Short from uploaded video"
        />
      </div>
    </div>
  );
}
