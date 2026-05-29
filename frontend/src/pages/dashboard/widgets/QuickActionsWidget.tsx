import { useNavigate } from 'react-router-dom';
import { Plus, TrendingUp, CalendarDays, Clapperboard } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { QuickActionTile } from '@/components/ui/QuickActionTile';

// ---------------------------------------------------------------------------
// QuickActionsWidget — 4-tile quick-action grid on the Dashboard
// ---------------------------------------------------------------------------

interface QuickActionsWidgetProps {
  seriesList: { id: string }[];
}

export function QuickActionsWidget({ seriesList }: QuickActionsWidgetProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();

  return (
    <div>
      <h2 className="text-xs font-display font-semibold text-txt-tertiary uppercase tracking-[0.15em] mb-3">
        {t('dashboard.widgets.quickActions.heading')}
      </h2>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <QuickActionTile
          icon={<Plus size={18} />}
          label={t('dashboard.widgets.quickActions.newSeries')}
          hint={t('dashboard.widgets.quickActions.newSeriesHint')}
          accent="accent"
          onClick={() => navigate('/series')}
          ariaLabel={t('dashboard.widgets.quickActions.newSeriesAria')}
        />
        <QuickActionTile
          icon={<TrendingUp size={18} />}
          label={t('dashboard.widgets.quickActions.trendingTopics')}
          hint={t('dashboard.widgets.quickActions.trendingTopicsHint')}
          accent="success"
          onClick={() => {
            const firstSeries = seriesList[0];
            if (firstSeries) {
              navigate(`/series/${firstSeries.id}?tab=trending`);
            } else {
              navigate('/series');
            }
          }}
          ariaLabel={t('dashboard.widgets.quickActions.trendingTopicsAria')}
        />
        <QuickActionTile
          icon={<CalendarDays size={18} />}
          label={t('dashboard.widgets.quickActions.calendar')}
          hint={t('dashboard.widgets.quickActions.calendarHint')}
          accent="info"
          onClick={() => navigate('/calendar')}
          ariaLabel={t('dashboard.widgets.quickActions.calendarAria')}
        />
        <QuickActionTile
          icon={<Clapperboard size={18} />}
          label={t('dashboard.widgets.quickActions.newFromVideo')}
          hint={t('dashboard.widgets.quickActions.newFromVideoHint')}
          accent="warning"
          onClick={() => navigate('/assets?ingest=1')}
          ariaLabel={t('dashboard.widgets.quickActions.newFromVideoAria')}
        />
      </div>
    </div>
  );
}
