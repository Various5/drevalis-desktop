import { useState, useEffect, useCallback } from 'react';
import { RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Spinner } from '@/components/ui/Spinner';
import { useToast } from '@/components/ui/Toast';
import { social as socialApi } from '@/lib/api';
import type { SocialPlatform } from '@/lib/api';
import { YouTubeSection } from './YouTubeSection';
import { PlatformCard } from './PlatformCard';
import type { SocialPlatformDef, ConnectFormState } from './PlatformCard';

const SOCIAL_PLATFORMS: SocialPlatformDef[] = [
  { id: 'tiktok', name: 'TikTok', colorClass: 'text-cyan-400', bgClass: 'bg-cyan-500/10', dotClass: 'bg-cyan-400', oauth: true },
  { id: 'instagram', name: 'Instagram', colorClass: 'text-pink-400', bgClass: 'bg-pink-500/10', dotClass: 'bg-pink-400' },
  { id: 'facebook', name: 'Facebook', colorClass: 'text-blue-400', bgClass: 'bg-blue-500/10', dotClass: 'bg-blue-400' },
  { id: 'x', name: 'X (Twitter)', colorClass: 'text-gray-300', bgClass: 'bg-gray-500/10', dotClass: 'bg-gray-300' },
];

export function SocialSection() {
  const { toast } = useToast();
  const [platforms, setPlatforms] = useState<SocialPlatform[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchPlatforms = useCallback(async () => {
    setLoading(true);
    try {
      const data = await socialApi.listPlatforms();
      setPlatforms(data);
    } catch (err) {
      toast.error('Failed to load social media accounts', { description: String(err) });
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void fetchPlatforms();
  }, [fetchPlatforms]);

  const handleConnect = useCallback(
    async (platformId: string, form: ConnectFormState) => {
      const meta: Record<string, string> = {};
      if (form.publicVideoBaseUrl?.trim()) {
        meta.public_video_base_url = form.publicVideoBaseUrl.trim();
      }
      await socialApi.connectPlatform({
        platform: platformId,
        account_name: form.accountName.trim(),
        account_id: form.accountId?.trim() || undefined,
        access_token: form.accessToken.trim(),
        refresh_token: form.refreshToken.trim() || undefined,
        account_metadata: Object.keys(meta).length ? meta : undefined,
      });
      toast.success('Account connected', { description: `${platformId} account linked` });
      void fetchPlatforms();
    },
    [fetchPlatforms, toast],
  );

  const handleDisconnect = useCallback(
    async (id: string) => {
      await socialApi.disconnectPlatform(id);
      toast.success('Account disconnected');
      void fetchPlatforms();
    },
    [fetchPlatforms, toast],
  );

  if (loading) return <Spinner />;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold text-txt-primary">
            Social Media Accounts
          </h3>
          <p className="text-sm text-txt-secondary mt-0.5">
            Connect your social media accounts to post content across platforms.
          </p>
        </div>
        <Button variant="ghost" size="sm" onClick={() => void fetchPlatforms()}>
          <RefreshCw size={14} />
          Refresh
        </Button>
      </div>

      {/* YouTube (OAuth-based) */}
      <YouTubeSection />

      {/* Other platforms (token-based) */}
      <div className="space-y-3">
        {SOCIAL_PLATFORMS.map((platformDef) => {
          const connected =
            platforms.find((p) => p.platform.toLowerCase() === platformDef.id) ?? null;
          return (
            <PlatformCard
              key={platformDef.id}
              platform={platformDef}
              connectedAccount={connected}
              onConnect={handleConnect}
              onDisconnect={handleDisconnect}
            />
          );
        })}
      </div>
    </div>
  );
}
