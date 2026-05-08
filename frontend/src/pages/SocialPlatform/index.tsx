/**
 * Generic social-platform dashboard page.
 *
 * Mirrors the YouTube page's shape (stats + uploads) but parameterized
 * by ``platform`` — one route per connected platform, only rendered
 * in the sidebar when that platform is actually connected.
 *
 * URL: ``/social/:platform`` where ``:platform`` ∈ {tiktok, instagram,
 * facebook, x}.
 */

import { useEffect, useMemo, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  Upload,
  TrendingUp,
  ExternalLink,
  Unlink,
  ArrowLeft,
} from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { Spinner } from '@/components/ui/Spinner';
import { useToast } from '@/components/ui/Toast';
import {
  SocialConnectWizard,
  type SocialPlatform as WizardPlatform,
} from '@/components/social/SocialConnectWizard';
import {
  social as socialApi,
  type SocialPlatform,
  type SocialUpload,
  type SocialPlatformStats,
} from '@/lib/api';

const PLATFORM_LABELS: Record<string, string> = {
  tiktok: 'TikTok',
  instagram: 'Instagram',
  facebook: 'Facebook',
  x: 'X',
};

function PlatformPage() {
  const { platform = '' } = useParams();
  const { toast } = useToast();

  const [account, setAccount] = useState<SocialPlatform | null>(null);
  const [accountLoading, setAccountLoading] = useState(true);
  const [uploads, setUploads] = useState<SocialUpload[]>([]);
  const [stats, setStats] = useState<SocialPlatformStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [wizardOpen, setWizardOpen] = useState(false);

  const label = PLATFORM_LABELS[platform] ?? platform;
  // Only YouTube + TikTok have a wizard spec today; the others fall
  // back to "open Settings" until their OAuth flows are wired.
  const wizardPlatform: WizardPlatform | null =
    platform === 'tiktok' ? 'tiktok' : null;

  useEffect(() => {
    let cancelled = false;
    setAccountLoading(true);
    setLoading(true);

    const load = async () => {
      try {
        const [platforms, allUploads, allStats] = await Promise.all([
          socialApi.listPlatforms(),
          socialApi.listUploads(),
          socialApi.getStats(),
        ]);
        if (cancelled) return;
        const acc = platforms.find(
          (p) => p.platform === platform && p.is_active,
        );
        setAccount(acc ?? null);
        setUploads(allUploads.filter((u) => u.platform === platform));
        setStats(allStats.find((s) => s.platform === platform) ?? null);
      } catch (err) {
        if (!cancelled) {
          toast.error(`Failed to load ${label}`, {
            description: String(err),
          });
        }
      } finally {
        if (!cancelled) {
          setAccountLoading(false);
          setLoading(false);
        }
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [platform, label, toast]);

  const recentUploads = useMemo(
    () =>
      [...uploads]
        .sort((a, b) => b.created_at.localeCompare(a.created_at))
        .slice(0, 10),
    [uploads],
  );

  const onDisconnect = async () => {
    if (!account) return;
    if (
      !confirm(
        `Disconnect ${label} account "${account.account_name ?? account.id}"? ` +
          'Uploads in progress will fail; scheduled posts will need to be re-targeted.',
      )
    ) {
      return;
    }
    try {
      await socialApi.disconnectPlatform(account.id);
      toast.success(`${label} disconnected`);
      setAccount(null);
    } catch (err) {
      toast.error('Disconnect failed', { description: String(err) });
    }
  };

  if (accountLoading) {
    return (
      <div className="flex items-center justify-center h-[40vh]">
        <Spinner size="lg" />
      </div>
    );
  }

  if (!account) {
    return (
      <div className="max-w-2xl mx-auto py-12 text-center">
        <h1 className="text-2xl font-display font-bold mb-2">
          {label} is not connected
        </h1>
        <p className="text-sm text-txt-secondary mb-6">
          {wizardPlatform
            ? `First time? Use the setup wizard to get your ${label} OAuth credentials and connect in one flow.`
            : `Connect your ${label} account in Settings → Social Media to see uploads, stats, and run cross-platform publishing from here.`}
        </p>
        <div className="flex items-center justify-center gap-3">
          {wizardPlatform && (
            <Button variant="primary" onClick={() => setWizardOpen(true)}>
              Setup wizard
            </Button>
          )}
          <Link to="/settings">
            <Button variant={wizardPlatform ? 'ghost' : 'primary'}>Open Settings</Button>
          </Link>
          <Link to="/">
            <Button variant="ghost">
              <ArrowLeft size={14} />
              Dashboard
            </Button>
          </Link>
        </div>
        {wizardPlatform && (
          <SocialConnectWizard
            open={wizardOpen}
            platform={wizardPlatform}
            onClose={() => setWizardOpen(false)}
            onConnected={() => {
              setWizardOpen(false);
              // Reload so the connected account picks up.
              window.location.reload();
            }}
          />
        )}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* ── Header ─────────────────────────────────────────── */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-display font-bold">{label}</h1>
          <p className="text-sm text-txt-secondary mt-1">
            Connected as{' '}
            <strong className="text-txt-primary">
              {account.account_name ?? account.id.slice(0, 8)}
            </strong>
            {' · '}
            <span className="text-txt-muted">
              since {new Date(account.created_at).toLocaleDateString()}
            </span>
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={onDisconnect}>
            <Unlink size={14} />
            Disconnect
          </Button>
        </div>
      </div>

      {/* ── Stat cards ─────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <Card className="p-4">
          <div className="text-xs text-txt-muted uppercase tracking-wider mb-1">
            Uploads
          </div>
          <div className="text-2xl font-display font-bold">
            {stats?.total_uploads ?? uploads.length}
          </div>
        </Card>
        <Card className="p-4">
          <div className="text-xs text-txt-muted uppercase tracking-wider mb-1">
            Views
          </div>
          <div className="text-2xl font-display font-bold">
            {(stats?.total_views ?? 0).toLocaleString()}
          </div>
        </Card>
        <Card className="p-4">
          <div className="text-xs text-txt-muted uppercase tracking-wider mb-1">
            Likes
          </div>
          <div className="text-2xl font-display font-bold">
            {(stats?.total_likes ?? 0).toLocaleString()}
          </div>
        </Card>
        <Card className="p-4">
          <div className="text-xs text-txt-muted uppercase tracking-wider mb-1">
            Comments
          </div>
          <div className="text-2xl font-display font-bold">
            {(stats?.total_comments ?? 0).toLocaleString()}
          </div>
        </Card>
        <Card className="p-4">
          <div className="text-xs text-txt-muted uppercase tracking-wider mb-1">
            Shares
          </div>
          <div className="text-2xl font-display font-bold">
            {(stats?.total_shares ?? 0).toLocaleString()}
          </div>
        </Card>
      </div>

      {/* ── Recent uploads ─────────────────────────────────── */}
      <Card className="p-5">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="font-display font-semibold">
              <Upload size={16} className="inline-block mr-2 -mt-1" />
              Recent uploads
            </h2>
            <p className="text-xs text-txt-secondary mt-1">
              Last 10 uploads to {label}.
            </p>
          </div>
          {uploads.length > 0 && (
            <Badge variant="default">{uploads.length} total</Badge>
          )}
        </div>

        {loading ? (
          <div className="py-8 flex justify-center">
            <Spinner />
          </div>
        ) : recentUploads.length === 0 ? (
          <p className="text-sm text-txt-muted text-center py-8">
            No uploads yet. Publish an episode to {label} from the episode
            detail page to see it here.
          </p>
        ) : (
          <div className="space-y-2">
            {recentUploads.map((u) => (
              <div
                key={u.id}
                className="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-bg-hover border border-border"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-medium text-txt-primary truncate">
                      {u.title || 'Untitled'}
                    </span>
                    <Badge
                      variant={
                        u.upload_status === 'done'
                          ? 'success'
                          : u.upload_status === 'failed'
                            ? 'error'
                            : 'default'
                      }
                      className="text-[10px]"
                    >
                      {u.upload_status}
                    </Badge>
                  </div>
                  <p className="text-[11px] text-txt-tertiary mt-0.5">
                    {new Date(u.created_at).toLocaleString()}
                    {u.views > 0 && (
                      <>
                        {' · '}
                        <TrendingUp
                          size={10}
                          className="inline-block -mt-0.5 mr-0.5"
                        />
                        {u.views.toLocaleString()} views
                      </>
                    )}
                  </p>
                </div>
                {u.remote_url && (
                  <a
                    href={u.remote_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-txt-tertiary hover:text-accent shrink-0"
                    aria-label={`Open on ${label}`}
                  >
                    <ExternalLink size={14} />
                  </a>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

export default PlatformPage;
