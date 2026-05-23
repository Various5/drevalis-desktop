import { useNavigate } from 'react-router-dom';
import { Rocket, Plus, Sparkles } from 'lucide-react';
import { Button } from '@/components/ui/Button';

/** First-run guidance shown on the Dashboard until the first series exists
 *  (Phase 3). Turns a "zero data" screen into a guided start: create a series,
 *  generate one with AI, or fork an example idea (prefills the AI generator). */

const EXAMPLE_IDEAS = [
  'Daily 60-second history mysteries',
  'Weekly explainers on space science',
  'Bite-size personal-finance tips',
];

export function FirstRunCard() {
  const navigate = useNavigate();

  return (
    <div className="rounded-xl border border-border-accent bg-accent-muted p-6">
      <div className="flex items-start gap-3">
        <div className="rounded-lg bg-accent/15 p-2 text-accent shrink-0">
          <Rocket size={20} />
        </div>
        <div className="flex-1 min-w-0">
          <h2 className="font-display text-lg font-semibold text-txt-primary">Start here</h2>
          <p className="mt-1 text-sm text-txt-secondary">
            Drevalis turns a series idea into a queue of ready-to-publish videos. Create your first
            series to begin — or fork an example to see how it works.
          </p>

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <Button variant="primary" size="sm" onClick={() => navigate('/series?create=true')}>
              <Plus size={14} />
              Create your first series
            </Button>
            <Button variant="secondary" size="sm" onClick={() => navigate('/series?ai=true')}>
              <Sparkles size={14} />
              Generate with AI
            </Button>
          </div>

          <div className="mt-4">
            <p className="mb-2 text-[11px] uppercase tracking-[0.15em] text-txt-tertiary">Example ideas</p>
            <div className="flex flex-wrap gap-2">
              {EXAMPLE_IDEAS.map((idea) => (
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
