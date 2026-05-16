import { useState, useEffect, useCallback } from 'react';
import { Youtube, Trash2, RefreshCw, Film, Smartphone } from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { Spinner } from '@/components/ui/Spinner';
import { SocialConnectWizard } from '@/components/social/SocialConnectWizard';
import { useToast } from '@/components/ui/Toast';
import { youtube } from '@/lib/api';

interface ChannelVideoStats {
  total: number;
  shorts_total: number;
  longform_total: number;
  last_synced_at: string | null;
}

function ChannelVideoSummary({ channelId }: { channelId: string }) {
  const { toast } = useToast();
  const [stats, setStats] = useState<ChannelVideoStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [resyncing, setResyncing] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await fetch(
        `/api/v1/youtube/channels/${channelId}/videos?limit=1`,
        { credentials: 'include' },
      );
      if (res.ok) {
        const j = (await res.json()) as ChannelVideoStats;
        setStats(j);
      }
    } catch {
      setStats(null);
    } finally {
      setLoading(false);
    }
  }, [channelId]);

  useEffect(() => {
    void load();
  }, [load]);

  const resync = async () => {
    setResyncing(true);
    try {
      const res = await fetch(
        `/api/v1/youtube/channels/${channelId}/resync`,
        { method: 'POST', credentials: 'include' },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      toast.success('Sync started — checking back in a few seconds');
      // Background-poll for ~30s. The worker usually finishes in <10s
      // for channels under 500 videos; we poll every 3s and stop on
      // either a stat change or the timeout.
      const before = stats?.last_synced_at ?? null;
      for (let i = 0; i < 10; i++) {
        await new Promise((r) => setTimeout(r, 3000));
        await load();
        if (stats?.last_synced_at && stats.last_synced_at !== before) break;
      }
    } catch (err) {
      toast.error('Resync failed', { description: String(err) });
    } finally {
      setResyncing(false);
    }
  };

  if (loading) {
    return (
      <div className="mt-2 text-xs text-txt-tertiary">Loading channel stats…</div>
    );
  }

  const synced = stats && (stats.total > 0 || stats.last_synced_at);

  return (
    <div className="mt-3 pt-3 border-t border-border">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-3 text-xs text-txt-secondary">
          {synced ? (
            <>
              <span className="inline-flex items-center gap-1">
                <Film size={12} className="text-txt-tertiary" />
                {stats?.longform_total ?? 0} long-form
              </span>
              <span className="inline-flex items-center gap-1">
                <Smartphone size={12} className="text-txt-tertiary" />
                {stats?.shorts_total ?? 0} shorts
              </span>
              <span className="text-txt-tertiary">
                · total {stats?.total ?? 0}
              </span>
            </>
          ) : (
            <span className="text-txt-tertiary italic">
              No channel videos synced yet. Click Resync to pull what's on YouTube.
            </span>
          )}
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => void resync()}
          disabled={resyncing}
          title="Re-enumerate this channel's videos from YouTube"
        >
          <RefreshCw size={12} className={resyncing ? 'animate-spin' : ''} />
          <span className="ml-1">{resyncing ? 'Syncing…' : 'Resync'}</span>
        </Button>
      </div>
      {synced && stats?.last_synced_at && (
        <div className="text-[10px] text-txt-tertiary mt-1">
          Last sync {new Date(stats.last_synced_at).toLocaleString()}
        </div>
      )}
    </div>
  );
}

interface YouTubeChannel {
  id: string;
  channel_id: string;
  channel_name: string;
  is_active: boolean;
  upload_days: string[] | null;
  upload_time: string | null;
}

const DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const;

export function YouTubeSection() {
  const { toast } = useToast();
  const [channels, setChannels] = useState<YouTubeChannel[]>([]);
  const [loading, setLoading] = useState(true);
  const [wizardOpen, setWizardOpen] = useState(false);

  const fetchChannels = async () => {
    try {
      const chs = await youtube.listChannels();
      setChannels(chs);
    } catch (err) {
      toast.error('Failed to load YouTube channels', { description: String(err) });
      setChannels([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void fetchChannels(); }, []);

  const handleConnect = () => {
    // Always go through the wizard. The previous "redirect the whole
    // webview to Google" path stranded the user on a JSON response
    // page after the second connect because Google's callback resolves
    // to the backend REST endpoint, not the SPA — there was no way
    // back without restarting the app. The wizard opens the OAuth URL
    // in the system browser instead, leaving the SPA alive to detect
    // the new channel by polling.
    setWizardOpen(true);
  };

  const handleDisconnect = async (channelId: string) => {
    try {
      await youtube.disconnect(channelId);
      toast.success('YouTube channel disconnected');
      setChannels((prev) => prev.filter((c) => c.id !== channelId));
    } catch (err) {
      toast.error('Failed to disconnect YouTube channel', { description: String(err) });
    }
  };

  const handleReconnect = (channelId: string) => {
    // Same flow as a fresh connect — opens the wizard, which sends the
    // OAuth URL to the system browser instead of nuking the SPA.
    try {
      sessionStorage.setItem('youtube_reconnect_target', channelId);
    } catch {
      /* sessionStorage unavailable in some embed contexts */
    }
    setWizardOpen(true);
  };

  const handleRemove = async (channelId: string, name: string) => {
    const ok = window.confirm(
      `Remove "${name}" completely?\n\nThis deletes the channel AND its upload history from this workspace. It does NOT touch the videos on YouTube itself.`,
    );
    if (!ok) return;
    try {
      await youtube.deleteChannel(channelId);
      toast.success(`Removed ${name}`);
      setChannels((prev) => prev.filter((c) => c.id !== channelId));
    } catch (err) {
      toast.error('Failed to remove YouTube channel', {
        description: String(err),
      });
    }
  };

  const handleUpdateSchedule = async (
    channelId: string,
    uploadDays: string[] | null,
    uploadTime: string | null,
  ) => {
    try {
      const updated = await youtube.updateChannel(channelId, {
        upload_days: uploadDays,
        upload_time: uploadTime,
      });
      setChannels((prev) =>
        prev.map((c) => (c.id === channelId ? { ...c, ...updated } : c)),
      );
    } catch (err) {
      toast.error('Failed to update upload schedule', { description: String(err) });
    }
  };

  if (loading) return <Spinner />;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <h3 className="text-lg font-semibold text-txt-primary">YouTube Channels</h3>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={() => setWizardOpen(true)}>
            Setup wizard
          </Button>
          <Button variant="primary" size="sm" onClick={handleConnect}>
            <Youtube size={14} /> Connect channel
          </Button>
        </div>
      </div>

      {channels.length === 0 ? (
        <Card padding="md">
          <p className="text-sm text-txt-secondary">
            No YouTube channels connected. First time? Use{' '}
            <button
              type="button"
              onClick={() => setWizardOpen(true)}
              className="text-accent hover:underline"
            >
              Setup wizard
            </button>{' '}
            to get your Google OAuth credentials and authorize a channel in
            one flow. Already have credentials? Click <strong>Connect Channel</strong>.
          </p>
        </Card>
      ) : (
        channels.map((ch) => (
          <Card key={ch.id} padding="md">
            <div className="flex items-center justify-between mb-3 gap-3 flex-wrap">
              <div className="flex items-center gap-2 min-w-0">
                <Youtube size={18} className="text-red-500 shrink-0" />
                <span className="text-sm font-semibold text-txt-primary truncate">
                  {ch.channel_name}
                </span>
                {ch.is_active ? (
                  <Badge variant="success" className="text-[10px]">Connected</Badge>
                ) : (
                  <Badge variant="warning" className="text-[10px]">Disconnected</Badge>
                )}
              </div>
              <div className="flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => void handleReconnect(ch.id)}
                  className="text-txt-secondary hover:text-accent"
                  title="Re-authorize this channel with Google (refreshes OAuth token)"
                >
                  Reconnect
                </Button>
                {ch.is_active && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => void handleDisconnect(ch.id)}
                    className="text-txt-tertiary hover:text-warning"
                    title="Wipe OAuth tokens but keep upload history"
                  >
                    Disconnect
                  </Button>
                )}
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => void handleRemove(ch.id, ch.channel_name)}
                  className="text-txt-tertiary hover:text-error"
                  title="Permanently remove this channel and its upload history"
                >
                  <Trash2 size={13} />
                </Button>
              </div>
            </div>

            {/* Upload schedule */}
            <div className="space-y-2 mt-2">
              <label className="text-xs font-medium text-txt-secondary">Upload Days</label>
              <div className="flex gap-1.5">
                {DAYS.map((day) => {
                  const active = (ch.upload_days ?? []).includes(day);
                  return (
                    <button
                      key={day}
                      type="button"
                      onClick={() => {
                        const newDays = active
                          ? (ch.upload_days ?? []).filter((d) => d !== day)
                          : [...(ch.upload_days ?? []), day];
                        void handleUpdateSchedule(ch.id, newDays.length > 0 ? newDays : null, ch.upload_time);
                      }}
                      className={[
                        'px-2 py-1 rounded text-[10px] font-medium uppercase transition',
                        active
                          ? 'bg-accent text-white'
                          : 'bg-bg-elevated text-txt-tertiary border border-border hover:border-border-hover',
                      ].join(' ')}
                    >
                      {day}
                    </button>
                  );
                })}
              </div>

              <label className="text-xs font-medium text-txt-secondary">Upload Time</label>
              <input
                type="time"
                value={ch.upload_time ?? ''}
                onChange={(e) =>
                  void handleUpdateSchedule(ch.id, ch.upload_days, e.target.value || null)
                }
                className="bg-bg-elevated border border-border rounded px-2 py-1 text-sm text-txt-primary w-32"
              />
            </div>

            {/* Synced channel videos — populated by sync_youtube_channel_videos
                after the OAuth callback. Resync button lets the user
                refresh on demand. */}
            {ch.is_active && <ChannelVideoSummary channelId={ch.id} />}
          </Card>
        ))
      )}

      <SocialConnectWizard
        open={wizardOpen}
        platform="youtube"
        onClose={() => setWizardOpen(false)}
        onConnected={() => {
          setWizardOpen(false);
          void fetchChannels();
        }}
      />
    </div>
  );
}
