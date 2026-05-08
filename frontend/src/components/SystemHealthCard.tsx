import { useNavigate } from 'react-router-dom';
import { AlertTriangle, ArrowRight } from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { useSystemHealth } from '@/lib/queries';

// ---------------------------------------------------------------------------
// Dashboard widget: surfaces degraded / unreachable services without
// making the user open Settings. Hidden when everything is healthy
// (no point burning real estate to say "all good"). The
// ``settings/health`` endpoint covers ComfyUI servers, LLM endpoints,
// voice models, FFmpeg, and storage paths.

export function SystemHealthCard() {
  const navigate = useNavigate();
  const q = useSystemHealth();

  const data = q.data;
  if (!data || data.overall === 'ok') return null;

  const problems = data.services.filter((s) => s.status !== 'ok');
  if (problems.length === 0) return null;

  const tone = data.overall === 'unhealthy' ? 'error' : 'warning';
  const toneClass =
    tone === 'error'
      ? 'border-error/30 bg-error/[0.05]'
      : 'border-warning/30 bg-warning/[0.05]';
  const iconColor = tone === 'error' ? 'text-error' : 'text-warning';

  return (
    <Card padding="md" className={toneClass}>
      <div className="flex items-start gap-3">
        <AlertTriangle size={18} className={`shrink-0 mt-0.5 ${iconColor}`} aria-hidden="true" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-sm font-display font-semibold text-txt-primary">
              {tone === 'error' ? 'System health: unhealthy' : 'System health: degraded'}
            </h3>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => navigate('/settings?section=health')}
              aria-label="Open settings to investigate"
            >
              Investigate
              <ArrowRight size={14} />
            </Button>
          </div>
          <ul className="mt-2 space-y-1">
            {problems.map((svc) => (
              <li key={svc.name} className="text-xs text-txt-secondary flex gap-2">
                <span className="font-medium capitalize text-txt-primary">{svc.name}</span>
                <span className="text-txt-tertiary">·</span>
                <span className="text-txt-secondary">{svc.message || svc.status}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </Card>
  );
}
