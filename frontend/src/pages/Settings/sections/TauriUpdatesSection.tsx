import { useCallback, useEffect, useState } from 'react';
import {
  ArrowUpCircle,
  CheckCircle2,
  AlertTriangle,
  RefreshCw,
  Search,
} from 'lucide-react';

import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { useToast } from '@/components/ui/Toast';
import {
  checkTauriUpdate,
  installTauriUpdate,
  type TauriUpdateInfo,
  type TauriUpdateProgress,
} from '@/lib/tauri';

/**
 * Desktop ("Tauri") update flow. Talks to the Tauri auto-updater plugin
 * which:
 *  - hits a signed manifest at the GitHub Releases URL configured in
 *    tauri.conf.json (plugins.updater.endpoints);
 *  - downloads + verifies + installs the update in place;
 *  - exits the running app and re-launches the new install.
 *
 * The user never has to re-download the installer manually. Replaces
 * the legacy Docker "pull new images and restart the stack" flow that
 * lives in UpdatesSection.tsx for the (deprecated) server install.
 */
export function TauriUpdatesSection() {
  const { toast } = useToast();
  const [info, setInfo] = useState<TauriUpdateInfo | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [progress, setProgress] = useState<TauriUpdateProgress | null>(null);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);

  const refresh = useCallback(
    async (surfaceResult: boolean) => {
      setRefreshing(true);
      try {
        const result = await checkTauriUpdate();
        setInfo(result);
        setLastChecked(new Date());
        if (surfaceResult) {
          if (result.available) {
            toast.success(`Update available: v${result.version}`);
          } else {
            toast.success("You're on the latest version", {
              description: result.currentVersion
                ? `Installed: v${result.currentVersion}`
                : undefined,
            });
          }
        }
      } catch (e) {
        toast.error('Update check failed', {
          description: e instanceof Error ? e.message : String(e),
        });
      } finally {
        setRefreshing(false);
      }
    },
    [toast],
  );

  // Initial fetch (no toast).
  useEffect(() => {
    void refresh(false);
  }, [refresh]);

  const onInstall = async () => {
    if (
      !confirm(
        'Download and install the update? The app will close, run the installer, and re-launch automatically.',
      )
    ) {
      return;
    }
    setInstalling(true);
    setProgress({ phase: 'started' });
    try {
      await installTauriUpdate((p) => setProgress(p));
      // If we get here without restart, surface a final toast.
      toast.success('Update installed', {
        description: 'Restart the app to use the new version.',
      });
    } catch (e) {
      toast.error('Install failed', {
        description: e instanceof Error ? e.message : String(e),
      });
    } finally {
      setInstalling(false);
    }
  };

  const downloadedMB =
    progress?.downloaded != null
      ? (progress.downloaded / 1024 / 1024).toFixed(1)
      : null;
  const totalMB =
    progress?.total != null ? (progress.total / 1024 / 1024).toFixed(1) : null;

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h3 className="text-lg font-semibold text-txt-primary flex items-center gap-2">
            <ArrowUpCircle size={18} /> Updates
          </h3>
          <p className="text-xs text-txt-secondary mt-1">
            Auto-update via the Drevalis GitHub Releases feed. The desktop
            app downloads, verifies, and installs in place.
          </p>
          {lastChecked && (
            <p className="text-[11px] text-txt-muted mt-1">
              Last checked: {lastChecked.toLocaleTimeString()}
            </p>
          )}
        </div>
        <Button
          variant="primary"
          size="md"
          onClick={() => refresh(true)}
          disabled={refreshing || installing}
          className="shrink-0"
        >
          <Search size={15} className={refreshing ? 'animate-pulse' : ''} />
          {refreshing ? 'Checking...' : 'Check for updates'}
        </Button>
      </div>

      <Card className="p-5 space-y-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-xs text-txt-secondary mb-1">Installed</div>
            <div className="text-lg font-semibold text-txt-primary">
              {info?.currentVersion ? `v${info.currentVersion}` : '-'}
            </div>
          </div>
          <div className="text-right">
            <div className="text-xs text-txt-secondary mb-1">Latest</div>
            <div className="text-lg font-semibold text-txt-primary">
              {info?.available && info.version
                ? `v${info.version}`
                : info?.currentVersion
                  ? `v${info.currentVersion}`
                  : '-'}
            </div>
          </div>
        </div>

        {info == null ? (
          <div className="p-3 rounded border border-white/10 bg-white/5 text-xs text-txt-secondary">
            Click "Check for updates" to query the release feed.
          </div>
        ) : info.available ? (
          <div className="p-3 rounded border border-accent/30 bg-accent/10 text-xs text-accent flex items-start gap-2">
            <ArrowUpCircle size={14} className="mt-0.5 shrink-0" />
            <div>
              <div className="font-semibold">Update available: v{info.version}</div>
              {info.body && (
                <pre className="mt-2 whitespace-pre-wrap font-sans text-[11px] text-accent/80 max-h-40 overflow-auto">
                  {info.body}
                </pre>
              )}
            </div>
          </div>
        ) : (
          <div className="p-3 rounded border border-success/30 bg-success/10 text-xs text-success flex items-center gap-2">
            <CheckCircle2 size={14} />
            You&apos;re on the latest version.
          </div>
        )}

        {installing && progress && (
          <div className="p-3 rounded border border-accent/30 bg-accent/10 text-xs text-accent">
            {progress.phase === 'started' && 'Starting download…'}
            {progress.phase === 'progress' && (
              <>
                Downloading {downloadedMB ?? '?'} MB
                {totalMB ? ` of ${totalMB} MB` : ''}
              </>
            )}
            {progress.phase === 'finished' && 'Installing…'}
          </div>
        )}

        <div className="flex items-center justify-between pt-3 border-t border-white/[0.06]">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => refresh(true)}
            disabled={refreshing || installing}
          >
            <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
            Check again
          </Button>
          <Button
            variant="primary"
            size="md"
            onClick={onInstall}
            disabled={installing || !info?.available}
          >
            {installing ? 'Installing...' : 'Update now'}
          </Button>
        </div>
      </Card>

      <div className="text-[11px] text-txt-muted flex items-start gap-2">
        <AlertTriangle size={12} className="mt-0.5 shrink-0" />
        <span>
          Update integrity is verified against an embedded public key. Releases
          must be signed with the matching private key (held by the maintainer
          / CI) for installation to proceed.
        </span>
      </div>
    </div>
  );
}
