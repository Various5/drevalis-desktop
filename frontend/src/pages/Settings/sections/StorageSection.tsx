import { useState, useEffect, useCallback } from 'react';
import { RefreshCw } from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Spinner } from '@/components/ui/Spinner';
import { useToast } from '@/components/ui/Toast';
import { settings as settingsApi } from '@/lib/api';
import type { StorageUsage } from '@/types';

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

export function StorageSection() {
  const { toast } = useToast();
  const [storage, setStorage] = useState<StorageUsage | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const fetchStorage = useCallback(async () => {
    try {
      const res = await settingsApi.storage();
      setStorage(res);
    } catch (err) {
      toast.error('Failed to load storage information', { description: String(err) });
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [toast]);

  useEffect(() => {
    void fetchStorage();
  }, [fetchStorage]);

  const handleRefresh = () => {
    setRefreshing(true);
    void fetchStorage();
  };

  if (loading) return <Spinner />;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-txt-primary">Storage</h3>
        <Button variant="ghost" size="sm" loading={refreshing} onClick={handleRefresh}>
          <RefreshCw size={14} />
          Refresh
        </Button>
      </div>

      {storage ? (
        <Card padding="md">
          <div className="grid grid-cols-2 gap-6">
            <div>
              <span className="text-xs text-txt-tertiary">Total Disk Usage</span>
              <p className="text-2xl font-bold text-txt-primary mt-0.5">
                {storage.total_size_human}
              </p>
              <p className="text-[10px] text-txt-tertiary mt-1">
                {storage.total_size_bytes.toLocaleString()} bytes
              </p>
            </div>
            <div>
              <span className="text-xs text-txt-tertiary">Storage Path (container)</span>
              <p className="text-sm text-txt-secondary font-mono mt-0.5 break-all">
                {storage.storage_base_abs || storage.storage_base_path}
              </p>
              {storage.host_source_path && (
                <>
                  <span className="text-xs text-txt-tertiary mt-3 block">
                    On host (copy media here)
                  </span>
                  <p className="text-sm text-accent font-mono mt-0.5 break-all">
                    {storage.host_source_path}
                  </p>
                  {(storage.host_source_path.startsWith('/project/') ||
                    storage.host_source_path.startsWith('/run/desktop/') ||
                    storage.host_source_path.startsWith('/mnt/host_mnt/')) && (
                    <p className="text-[11px] text-txt-tertiary mt-1">
                      That's Docker Desktop's Linux-VM label for the compose
                      file's directory. On Windows it's the same folder as{' '}
                      <code className="text-txt-secondary">
                        %USERPROFILE%\Drevalis\storage\
                      </code>
                      ; on macOS it's{' '}
                      <code className="text-txt-secondary">
                        ~/Drevalis/storage/
                      </code>
                      .
                    </p>
                  )}
                </>
              )}
            </div>
          </div>
          {storage.subdir_sizes && Object.keys(storage.subdir_sizes).length > 0 && (
            <div className="mt-6 pt-4 border-t border-border">
              <p className="text-xs text-txt-tertiary mb-2">Subdirectory breakdown</p>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
                {Object.entries(storage.subdir_sizes)
                  .sort((a, b) => b[1] - a[1])
                  .map(([name, size]) => (
                    <div
                      key={name}
                      className="rounded bg-bg-elevated p-2 font-mono"
                    >
                      <div className="text-txt-primary">{name}</div>
                      <div
                        className={
                          size > 0 ? 'text-txt-secondary' : 'text-txt-tertiary'
                        }
                      >
                        {formatBytes(size)}
                      </div>
                    </div>
                  ))}
              </div>
              {storage.total_size_bytes < 10 * 1024 * 1024 && (
                <p className="mt-3 text-xs text-amber-300 bg-amber-500/10 p-2 rounded border border-amber-500/30">
                  Storage is nearly empty. If you copied media files to your
                  host, make sure the destination is
                  {storage.host_source_path && (
                    <> <code className="font-mono">{storage.host_source_path}</code></>
                  )}
                  {' — '}
                  the app only sees files under the bind-mounted directory.
                  Copying elsewhere (e.g. a sibling folder with a different
                  case, or a drive the compose file doesn't map) won't be
                  picked up.
                </p>
              )}
              {storage.mountinfo_lines && storage.mountinfo_lines.length > 0 && (
                <details className="mt-3 rounded bg-bg-elevated p-3 text-[11px]">
                  <summary className="cursor-pointer text-txt-secondary">
                    Raw mount info ({storage.mountinfo_lines.length} lines) — paste for support
                  </summary>
                  <pre className="mt-2 font-mono text-[10px] text-txt-primary whitespace-pre-wrap break-all leading-relaxed">
                    {storage.mountinfo_lines.join('\n')}
                  </pre>
                  <p className="mt-2 text-[11px] text-txt-secondary leading-relaxed">
                    The 4th whitespace-separated field of the ``/app/storage``
                    line is the host source path Docker recorded. If it doesn't
                    match the directory where your 21 GB lives, the containers
                    were started from a different folder. Stop them, cd to the
                    directory that HAS your files + the docker-compose.yml,
                    then ``docker compose up -d`` from there.
                  </p>
                </details>
              )}
            </div>
          )}
        </Card>
      ) : (
        <Card padding="md">
          <p className="text-sm text-txt-secondary">
            Unable to fetch storage information.
          </p>
        </Card>
      )}
    </div>
  );
}
