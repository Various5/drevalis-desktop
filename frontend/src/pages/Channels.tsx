import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Youtube,
  Music2,
  Instagram,
  Facebook,
  Twitter,
  Link2,
  Settings2,
  type LucideIcon,
} from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { useConnectedPlatforms } from '@/lib/useConnectedPlatforms';

// ---------------------------------------------------------------------------
// Channels — unified publishing-channel hub (Phase 1)
// ---------------------------------------------------------------------------
//
// Before this page the sidebar only showed YouTube / TikTok / Instagram /
// Facebook / X *after* they were connected — so a new user had no way to
// discover that those integrations exist (connect lived buried in
// Settings → Integrations → Social Media). This hub is always reachable
// from the sidebar and lists every supported platform with its connection
// status + an entry point. Manage/Connect deep-link to the platform's
// existing page, which owns the actual OAuth / token flow.
//
// See docs/decisions/001-channels-hub.md.

interface PlatformDef {
  id: string;
  label: string;
  icon: LucideIcon;
  /** Per-platform management/connect route. */
  route: string;
  /** Tailwind classes for the icon chip. */
  iconColor: string;
  iconBg: string;
}

const PLATFORMS: PlatformDef[] = [
  { id: 'youtube', label: 'YouTube', icon: Youtube, route: '/youtube', iconColor: 'text-red-400', iconBg: 'bg-red-500/10' },
  { id: 'tiktok', label: 'TikTok', icon: Music2, route: '/social/tiktok', iconColor: 'text-fuchsia-300', iconBg: 'bg-fuchsia-500/10' },
  { id: 'instagram', label: 'Instagram', icon: Instagram, route: '/social/instagram', iconColor: 'text-pink-400', iconBg: 'bg-pink-500/10' },
  { id: 'facebook', label: 'Facebook', icon: Facebook, route: '/social/facebook', iconColor: 'text-blue-400', iconBg: 'bg-blue-500/10' },
  { id: 'x', label: 'X', icon: Twitter, route: '/social/x', iconColor: 'text-txt-primary', iconBg: 'bg-white/10' },
];

function ChannelCard({
  platform,
  connected,
  onOpen,
}: {
  platform: PlatformDef;
  connected: boolean;
  onOpen: (route: string) => void;
}) {
  const Icon = platform.icon;
  const { t } = useTranslation();
  return (
    <Card padding="md">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <div className={['w-10 h-10 rounded-lg flex items-center justify-center shrink-0', platform.iconBg].join(' ')}>
            <Icon size={20} className={platform.iconColor} />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-txt-primary">{platform.label}</p>
            {connected ? (
              <Badge variant="success" dot>
                {t('channels.connected')}
              </Badge>
            ) : (
              <Badge variant="neutral">{t('channels.notConnected')}</Badge>
            )}
          </div>
        </div>
        <Button
          variant={connected ? 'ghost' : 'secondary'}
          size="sm"
          onClick={() => onOpen(platform.route)}
          aria-label={
            connected
              ? t('channels.managePlatform', { platform: platform.label })
              : t('channels.connectPlatform', { platform: platform.label })
          }
        >
          {connected ? (
            <>
              <Settings2 size={13} />
              {t('channels.manage')}
            </>
          ) : (
            <>
              <Link2 size={13} />
              {t('channels.connect')}
            </>
          )}
        </Button>
      </div>
    </Card>
  );
}

function Channels() {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { socials, youtubeConnected, ready } = useConnectedPlatforms();

  const isConnected = (id: string): boolean =>
    id === 'youtube' ? youtubeConnected : socials.includes(id);

  return (
    <div>
      <div className="mb-6">
        <p className="text-sm text-txt-secondary">{t('channels.intro')}</p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {PLATFORMS.map((p) => (
          <ChannelCard
            key={p.id}
            platform={p}
            connected={ready && isConnected(p.id)}
            onOpen={(route) => navigate(route)}
          />
        ))}
      </div>
    </div>
  );
}

export default Channels;
