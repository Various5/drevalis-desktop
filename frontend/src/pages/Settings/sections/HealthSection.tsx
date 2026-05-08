import { useState, useEffect, useCallback } from 'react';
import { CheckCircle2, AlertCircle, XCircle, RefreshCw } from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { Spinner } from '@/components/ui/Spinner';
import { useToast } from '@/components/ui/Toast';
import { settings as settingsApi } from '@/lib/api';
import type { HealthCheck } from '@/types';

export function HealthSection() {
  const { toast } = useToast();
  const [health, setHealth] = useState<HealthCheck | null>(null);
  const [loading, setLoading] = useState(true);

  const fetch = useCallback(async () => {
    setLoading(true);
    try {
      const res = await settingsApi.health();
      setHealth(res);
    } catch (err) {
      toast.error('Failed to load system health', { description: String(err) });
    } finally {
      setLoading(false);
    }
  }, [toast]);

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
        <h3 className="text-lg font-semibold text-txt-primary">System Health</h3>
        <Button variant="ghost" size="sm" onClick={() => void fetch()}>
          <RefreshCw size={14} />
          Refresh
        </Button>
      </div>

      {health && (
        <>
          <Card padding="md">
            <div className="flex items-center gap-3">
              {statusIcon(health.overall)}
              <span className="text-md font-semibold text-txt-primary">
                Overall: {health.overall}
              </span>
              <Badge variant={health.overall}>{health.overall}</Badge>
            </div>
          </Card>

          <div className="space-y-2">
            {health.services.map((svc) => (
              <Card key={svc.name} padding="sm">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    {statusIcon(svc.status)}
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
                    <Badge variant={svc.status}>{svc.status}</Badge>
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
