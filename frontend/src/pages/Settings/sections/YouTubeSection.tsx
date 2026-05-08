import { useState, useEffect } from 'react';
import { Youtube, Trash2 } from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { Spinner } from '@/components/ui/Spinner';
import { SocialConnectWizard } from '@/components/social/SocialConnectWizard';
import { useToast } from '@/components/ui/Toast';
import { youtube } from '@/lib/api';

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

  const handleConnect = async () => {
    try {
      const data = await youtube.getAuthUrl();
      window.location.href = data.auth_url;
    } catch (err: unknown) {
      const status = (err as { status?: number })?.status;
      if (status === 503 || status === 400) {
        setWizardOpen(true);
        return;
      }
      toast.error('Failed to start YouTube connection', { description: String(err) });
    }
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

  const handleReconnect = async (channelId: string) => {
    try {
      const data = await youtube.getAuthUrl();
      try {
        sessionStorage.setItem('youtube_reconnect_target', channelId);
      } catch { /* ignore */ }
      window.location.href = data.auth_url;
    } catch (err) {
      toast.error('Failed to start YouTube reconnection', {
        description: String(err),
      });
    }
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
          <Button variant="primary" size="sm" onClick={() => void handleConnect()}>
            <Youtube size={14} /> Connect Channel
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
