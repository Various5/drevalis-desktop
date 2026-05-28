import { useState, useEffect, useCallback } from 'react';
import { CheckCircle2, AlertCircle, XCircle, RefreshCw } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { Spinner } from '@/components/ui/Spinner';
import { useToast } from '@/components/ui/Toast';
import { settings as settingsApi } from '@/lib/api';
import type { HealthCheck } from '@/types';

export function HealthSection() {
  const { toast } = useToast();
  const { t } = useTranslation();
  const [health, setHealth] = useState<HealthCheck | null>(null);
  const [loading, setLoading] = useState(true);

  /** Translate a backend status enum (ok/degraded/unhealthy/unreachable) for
   *  display. Unknown values fall back to the raw enum so we never hide
   *  diagnostic info behind a missing translation. */
  const localiseStatus = (s: string): string => {
    const key = `common.status.${s}`;
    const out = t(key);
    return out === key ? s : out;
  };

  const fetch = useCallback(async () => {
    setLoading(true);
    try {
      const res = await settingsApi.health();
      setHealth(res);
    } catch (err) {
      toast.error(t('settings.health.loadFailed'), { description: String(err) });
    } finally {
      setLoading(false);
    }
  }, [toast, t]);

  useEffect(() => {
    void fetch();
  }, [fetch]);

  if (loading) return <Spinner />;

  const statusIcon = (status: string) => {
    if (status === 'ok') return <CheckCircle2 size={16} className="text-success" />;
    if (status === 'degraded') return <AlertCircle size={16} className="text-warning" />;
    return <XCircle size={16} className="text-error" />;
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-txt-primary">{t('settings.health.title')}</h3>
        <Button variant="ghost" size="sm" onClick={() => void fetch()}>
          <RefreshCw size={14} />
          {t('settings.health.refresh')}
        </Button>
      </div>

      {health && (
        <>
          <Card padding="md">
            <div className="flex items-center gap-3">
              {statusIcon(health.overall)}
              <span className="text-md font-semibold text-txt-primary">
                {t('settings.health.overall', { status: localiseStatus(health.overall) })}
              </span>
              <Badge variant={health.overall}>{localiseStatus(health.overall)}</Badge>
            </div>
          </Card>

          <div className="space-y-2">
            {health.services.map((svc) => (
              <Card key={svc.name} padding="sm">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    {statusIcon(svc.status)}
                    {/* Service names (Redis, ComfyUI, FFmpeg, …) are proper
                        nouns — never translated. */}
                    <span className="text-sm font-medium text-txt-primary capitalize">
                      {svc.name}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    {svc.message && (
                      <span className="text-xs text-txt-tertiary max-w-xs text-truncate">
                        {svc.message}
                      </span>
                    )}
                    <Badge variant={svc.status}>{localiseStatus(svc.status)}</Badge>
                  </div>
                </div>
              </Card>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
