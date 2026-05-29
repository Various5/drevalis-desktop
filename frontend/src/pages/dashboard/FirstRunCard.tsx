import { useNavigate } from 'react-router-dom';
import { Rocket, Plus, Sparkles } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/Button';

/** First-run guidance shown on the Dashboard until the first series exists
 *  (Phase 3). Turns a "zero data" screen into a guided start: create a series,
 *  generate one with AI, or fork an example idea (prefills the AI generator). */

export function FirstRunCard() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const examples = t('dashboard.firstRun.examples', { returnObjects: true }) as string[];

  return (
    <div className="rounded-xl border border-border-accent bg-accent-muted p-6">
      <div className="flex items-start gap-3">
        <div className="rounded-lg bg-accent/15 p-2 text-accent shrink-0">
          <Rocket size={20} />
        </div>
        <div className="flex-1 min-w-0">
          <h2 className="font-display text-lg font-semibold text-txt-primary">{t('dashboard.firstRun.title')}</h2>
          <p className="mt-1 text-sm text-txt-secondary">
            {t('dashboard.firstRun.body')}
          </p>

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <Button variant="primary" size="sm" onClick={() => navigate('/series?create=true')}>
              <Plus size={14} />
              {t('dashboard.firstRun.createFirstSeries')}
            </Button>
            <Button variant="secondary" size="sm" onClick={() => navigate('/series?ai=true')}>
              <Sparkles size={14} />
              {t('dashboard.firstRun.generateWithAi')}
            </Button>
          </div>

          <div className="mt-4">
            <p className="mb-2 text-[11px] uppercase tracking-[0.15em] text-txt-tertiary">{t('dashboard.firstRun.exampleIdeasLabel')}</p>
            <div className="flex flex-wrap gap-2">
              {examples.map((idea) => (
                <button
                  key={idea}
                  onClick={() => navigate(`/series?ai=true&idea=${encodeURIComponent(idea)}`)}
                  className="rounded-full border border-border bg-bg-surface px-3 py-1 text-xs text-txt-secondary hover:text-txt-primary hover:border-border-hover"
                >
                  {idea}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
