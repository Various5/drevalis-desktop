import { useState, useEffect, useCallback } from 'react';
import { Youtube, Trash2, RefreshCw, Film, Smartphone } from 'lucide-react';
import { Trans, useTranslation } from 'react-i18next';
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
  const { t } = useTranslation();
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
      toast.success(t('settings.youtube.videos.syncStarted'));
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
      toast.error(t('settings.youtube.videos.resyncFailed'), { description: String(err) });
    } finally {
      setResyncing(false);
    }
  };

  if (loading) {
    return (
      <div className="mt-2 text-xs text-txt-tertiary">{t('settings.youtube.videos.loading')}</div>
    );
  }

  // Three distinct states the user needs to see:
  //   1. Never synced (no rows AND no Redis marker → ``last_synced_at``
  //      is null) — prompt them to sync.
  //   2. Synced + has videos (total > 0) — show the stat row.
  //   3. Synced + empty (last_synced_at is set, total === 0) — call
  //      out that the channel has no uploads yet so the user doesn't
  //      think the sync silently broke.
  const hasSynced = stats !== null && Boolean(stats.last_synced_at);
  const hasVideos = (stats?.total ?? 0) > 0;

  return (
    <div className="mt-3 pt-3 border-t border-border">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-3 text-xs text-txt-secondary">
          {hasVideos ? (
            <>
              <span className="inline-flex items-center gap-1">
                <Film size={12} className="text-txt-tertiary" />
                {t('settings.youtube.videos.longForm', { count: stats?.longform_total ?? 0 })}
              </span>
              <span className="inline-flex items-center gap-1">
                <Smartphone size={12} className="text-txt-tertiary" />
                {t('settings.youtube.videos.shorts', { count: stats?.shorts_total ?? 0 })}
              </span>
              <span className="text-txt-tertiary">
                {t('settings.youtube.videos.totalSuffix', { count: stats?.total ?? 0 })}
              </span>
            </>
          ) : hasSynced ? (
            <span className="text-txt-tertiary italic">
              {t('settings.youtube.videos.syncedEmpty')}
            </span>
          ) : (
            <span className="text-txt-tertiary italic">
              {t('settings.youtube.videos.neverSynced')}
            </span>
          )}
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => void resync()}
          disabled={resyncing}
          title={t('settings.youtube.videos.resyncTitle')}
        >
          <RefreshCw size={12} className={resyncing ? 'animate-spin' : ''} />
          <span className="ml-1">{resyncing ? t('settings.youtube.videos.syncing') : t('settings.youtube.videos.resync')}</span>
        </Button>
      </div>
      {hasSynced && stats?.last_synced_at && (
        <div className="text-[10px] text-txt-tertiary mt-1">
          {t('settings.youtube.videos.lastSync', { when: new Date(stats.last_synced_at).toLocaleString() })}
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
  const { t } = useTranslation();
  const { toast } = useToast();
  const [channels, setChannels] = useState<YouTubeChannel[]>([]);
  const [loading, setLoading] = useState(true);
  const [wizardOpen, setWizardOpen] = useState(false);

  const fetchChannels = async () => {
    try {
      const chs = await youtube.listChannels();
      setChannels(chs);
    } catch (err) {
      toast.error(t('settings.youtube.loadFailed'), { description: String(err) });
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
      toast.success(t('settings.youtube.disconnectedToast'));
      setChannels((prev) => prev.filter((c) => c.id !== channelId));
    } catch (err) {
      toast.error(t('settings.youtube.disconnectFailed'), { description: String(err) });
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
    const ok = window.confirm(t('settings.youtube.removeConfirm', { name }));
    if (!ok) return;
    try {
      await youtube.deleteChannel(channelId);
      toast.success(t('settings.youtube.removedToast', { name }));
      setChannels((prev) => prev.filter((c) => c.id !== channelId));
    } catch (err) {
      toast.error(t('settings.youtube.removeFailed'), { description: String(err) });
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
      toast.error(t('settings.youtube.scheduleUpdateFailed'), { description: String(err) });
    }
  };

  if (loading) return <Spinner />;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <h3 className="text-lg font-semibold text-txt-primary">{t('settings.youtube.heading')}</h3>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={() => setWizardOpen(true)}>
            {t('settings.youtube.setupWizard')}
          </Button>
          <Button variant="primary" size="sm" onClick={handleConnect}>
            <Youtube size={14} /> {t('settings.youtube.connectChannel')}
          </Button>
        </div>
      </div>

      {channels.length === 0 ? (
        <Card padding="md">
          <p className="text-sm text-txt-secondary">
            <Trans
              i18nKey="settings.youtube.emptyIntro"
              components={{
                1: (
                  <button
                    type="button"
                    onClick={() => setWizardOpen(true)}
                    className="text-accent hover:underline"
                  />
                ),
                2: <strong />,
              }}
            />
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
                  <Badge variant="success" className="text-[10px]">{t('settings.youtube.channel.connected')}</Badge>
                ) : (
                  <Badge variant="warning" className="text-[10px]">{t('settings.youtube.channel.disconnected')}</Badge>
                )}
              </div>
              <div className="flex items-center gap-1">
                <SyncChannelButton channelId={ch.id} />
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => void handleReconnect(ch.id)}
                  className="text-txt-secondary hover:text-accent"
                  title={t('settings.youtube.channel.reconnectTitle')}
                >
                  {t('settings.youtube.channel.reconnect')}
                </Button>
                {ch.is_active && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => void handleDisconnect(ch.id)}
                    className="text-txt-tertiary hover:text-warning"
                    title={t('settings.youtube.channel.disconnectTitle')}
                  >
                    {t('settings.youtube.channel.disconnect')}
                  </Button>
                )}
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => void handleRemove(ch.id, ch.channel_name)}
                  className="text-txt-tertiary hover:text-error"
                  title={t('settings.youtube.channel.removeTitle')}
                >
                  <Trash2 size={13} />
                </Button>
              </div>
            </div>

            {/* Upload schedule */}
            <div className="space-y-2 mt-2">
              <label className="text-xs font-medium text-txt-secondary">{t('settings.youtube.channel.uploadDays')}</label>
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
                      {t(`settings.youtube.channel.days.${day}`)}
                    </button>
                  );
                })}
              </div>

              <label className="text-xs font-medium text-txt-secondary">{t('settings.youtube.channel.uploadTime')}</label>
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
                after the OAuth callback. Always rendered (even for
                disconnected channels) so the user can see the last
                sync state and trigger a fresh one once they
                reconnect. */}
            <ChannelVideoSummary channelId={ch.id} />
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

// Single-button sync trigger for the channel-card header row. Sits
// next to Reconnect / Disconnect so the user can fire a sync from the
// most channel-actiony place in the UI, regardless of how the
// ``ChannelVideoSummary`` widget below is rendering.
function SyncChannelButton({ channelId }: { channelId: string }) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const [syncing, setSyncing] = useState(false);
  const trigger = async () => {
    setSyncing(true);
    try {
      const res = await fetch(`/api/v1/youtube/channels/${channelId}/resync`, {
        method: 'POST',
        credentials: 'include',
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      toast.success(t('settings.youtube.sync.syncQueued'));
    } catch (err) {
      toast.error(t('settings.youtube.sync.syncFailed'), { description: String(err) });
    } finally {
      setSyncing(false);
    }
  };
  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={() => void trigger()}
      disabled={syncing}
      className="text-txt-secondary hover:text-accent"
      title={t('settings.youtube.sync.title')}
    >
      <RefreshCw size={13} className={syncing ? 'animate-spin' : ''} />
      <span className="ml-1">{syncing ? t('settings.youtube.sync.syncing') : t('settings.youtube.sync.label')}</span>
    </Button>
  );
}
