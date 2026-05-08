import { useState } from 'react';
import {
  AlertCircle,
  ChevronUp,
  Plus,
  Link2,
  Unlink,
} from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Badge } from '@/components/ui/Badge';
import { SocialConnectWizard } from '@/components/social/SocialConnectWizard';
import { social as socialApi } from '@/lib/api';
import type { SocialPlatform } from '@/lib/api';

// ---------------------------------------------------------------------------
// Shared types used by both YouTubeSection and SocialSection
// ---------------------------------------------------------------------------

export interface SocialPlatformDef {
  id: string;
  name: string;
  colorClass: string;
  bgClass: string;
  dotClass: string;
  oauth?: boolean;
}

export interface ConnectFormState {
  accountName: string;
  accountId: string;
  accessToken: string;
  refreshToken: string;
  publicVideoBaseUrl: string;
}

export interface PlatformCardProps {
  platform: SocialPlatformDef;
  connectedAccount: SocialPlatform | null;
  onConnect: (platform: string, form: ConnectFormState) => Promise<void>;
  onDisconnect: (platformId: string) => Promise<void>;
}

export function PlatformCard({
  platform,
  connectedAccount,
  onConnect,
  onDisconnect,
}: PlatformCardProps) {
  const [formOpen, setFormOpen] = useState(false);
  const [accountName, setAccountName] = useState('');
  const [accountId, setAccountId] = useState('');
  const [accessToken, setAccessToken] = useState('');
  const [refreshToken, setRefreshToken] = useState('');
  const [publicVideoBaseUrl, setPublicVideoBaseUrl] = useState('');
  const [connecting, setConnecting] = useState(false);
  const [wizardOpen, setWizardOpen] = useState(false);

  const needsAccountId = platform.id === 'facebook' || platform.id === 'instagram';
  const needsPublicUrl = platform.id === 'instagram';
  const [disconnecting, setDisconnecting] = useState(false);
  const [connectError, setConnectError] = useState<string | null>(null);

  const handleConnect = async () => {
    if (platform.oauth) {
      setConnecting(true);
      setConnectError(null);
      try {
        if (platform.id === 'tiktok') {
          const data = await socialApi.tiktokAuthUrl();
          window.location.href = data.auth_url;
        }
      } catch (err: unknown) {
        const status = (err as { status?: number })?.status;
        if (
          platform.id === 'tiktok' &&
          (status === 400 || status === 503)
        ) {
          setWizardOpen(true);
          setConnecting(false);
          return;
        }
        setConnectError(err instanceof Error ? err.message : 'Failed to start OAuth flow.');
        setConnecting(false);
      }
      return;
    }

    if (!accountName.trim() || !accessToken.trim()) return;
    if (needsAccountId && !accountId.trim()) {
      setConnectError(
        platform.id === 'facebook'
          ? 'Facebook needs the numeric Page ID.'
          : 'Instagram needs the Business/Creator account ID.',
      );
      return;
    }
    if (needsPublicUrl && !publicVideoBaseUrl.trim()) {
      setConnectError(
        'Instagram Reels need a public HTTPS URL that maps to your storage folder.',
      );
      return;
    }
    setConnecting(true);
    setConnectError(null);
    try {
      await onConnect(platform.id, {
        accountName,
        accountId,
        accessToken,
        refreshToken,
        publicVideoBaseUrl,
      });
      setFormOpen(false);
      setAccountName('');
      setAccountId('');
      setAccessToken('');
      setRefreshToken('');
      setPublicVideoBaseUrl('');
    } catch (err) {
      setConnectError(err instanceof Error ? err.message : 'Failed to connect.');
    } finally {
      setConnecting(false);
    }
  };

  const handleDisconnect = async () => {
    if (!connectedAccount) return;
    setDisconnecting(true);
    try {
      await onDisconnect(connectedAccount.id);
    } catch {
      // swallow — parent state will remain until next reload
    } finally {
      setDisconnecting(false);
    }
  };

  const isConnected = connectedAccount !== null;

  return (
    <Card padding="md">
      {/* Platform header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className={['w-9 h-9 rounded-lg flex items-center justify-center shrink-0', platform.bgClass].join(' ')}>
            <span className={['w-3 h-3 rounded-full', platform.dotClass].join(' ')} />
          </div>
          <div>
            <p className={['text-sm font-semibold', platform.colorClass].join(' ')}>
              {platform.name}
            </p>
            {isConnected && connectedAccount?.account_name ? (
              <p className="text-xs text-txt-tertiary">
                @{connectedAccount.account_name}
              </p>
            ) : (
              <p className="text-xs text-txt-tertiary">Not connected</p>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {isConnected ? (
            <>
              <Badge variant="success" dot>
                Connected
              </Badge>
              <Button
                variant="ghost"
                size="sm"
                loading={disconnecting}
                onClick={() => void handleDisconnect()}
                className="text-txt-tertiary hover:text-error"
                aria-label={`Disconnect ${platform.name}`}
              >
                <Unlink size={13} />
                Disconnect
              </Button>
            </>
          ) : (
            <>
              <Badge variant="neutral">Not connected</Badge>
              {platform.id === 'tiktok' && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setWizardOpen(true)}
                  title="Walks you through getting TikTok OAuth credentials"
                >
                  Setup wizard
                </Button>
              )}
              <Button
                variant="secondary"
                size="sm"
                loading={platform.oauth ? connecting : undefined}
                onClick={() => platform.oauth ? void handleConnect() : setFormOpen((v) => !v)}
                aria-expanded={platform.oauth ? undefined : formOpen}
                aria-controls={platform.oauth ? undefined : `connect-form-${platform.id}`}
              >
                {platform.oauth ? (
                  <>
                    <Link2 size={13} />
                    Connect {platform.name}
                  </>
                ) : formOpen ? (
                  <>
                    <ChevronUp size={13} />
                    Cancel
                  </>
                ) : (
                  <>
                    <Plus size={13} />
                    Connect
                  </>
                )}
              </Button>
            </>
          )}
        </div>
      </div>

      {/* Connect form (inline, collapsible) */}
      {!isConnected && formOpen && (
        <div
          id={`connect-form-${platform.id}`}
          className="mt-4 space-y-3 pt-4 border-t border-border"
          role="group"
          aria-label={`Connect ${platform.name} account`}
        >
          <div>
            <label
              htmlFor={`${platform.id}-account-name`}
              className="block text-xs font-medium text-txt-secondary mb-1"
            >
              Account Name
            </label>
            <Input
              id={`${platform.id}-account-name`}
              value={accountName}
              onChange={(e) => setAccountName(e.target.value)}
              placeholder="yourhandle"
              aria-required="true"
            />
          </div>

          {needsAccountId && (
            <div>
              <label
                htmlFor={`${platform.id}-account-id`}
                className="block text-xs font-medium text-txt-secondary mb-1"
              >
                {platform.id === 'facebook' ? 'Facebook Page ID' : 'Instagram Account ID'}
                <span className="text-error ml-1">*</span>
              </label>
              <Input
                id={`${platform.id}-account-id`}
                value={accountId}
                onChange={(e) => setAccountId(e.target.value)}
                placeholder={
                  platform.id === 'facebook'
                    ? 'e.g. 102034567890123'
                    : 'e.g. 17841400000000000'
                }
                aria-required="true"
              />
              <p className="text-[11px] text-txt-tertiary mt-1">
                {platform.id === 'facebook'
                  ? 'Numeric ID of the Page you want uploads to land on. Get it from facebook.com/{your-page}/about.'
                  : 'Business/Creator account ID from Meta Graph — required to create Reels containers.'}
              </p>
            </div>
          )}

          <div>
            <label
              htmlFor={`${platform.id}-access-token`}
              className="block text-xs font-medium text-txt-secondary mb-1"
            >
              {platform.id === 'facebook' ? 'Page Access Token' : 'API Access Token'}
              <span className="text-error ml-1">*</span>
            </label>
            <Input
              id={`${platform.id}-access-token`}
              type="password"
              value={accessToken}
              onChange={(e) => setAccessToken(e.target.value)}
              placeholder={
                platform.id === 'facebook'
                  ? 'Page Access Token (not a user token)'
                  : 'Paste your access token...'
              }
              aria-required="true"
            />
            {platform.id === 'facebook' && (
              <p className="text-[11px] text-txt-tertiary mt-1">
                Exchange a user token for a long-lived Page Access Token via Graph
                API's <code>/me/accounts</code>. User tokens will fail on upload.
              </p>
            )}
          </div>

          {needsPublicUrl && (
            <div>
              <label
                htmlFor={`${platform.id}-public-url`}
                className="block text-xs font-medium text-txt-secondary mb-1"
              >
                Public video base URL
                <span className="text-error ml-1">*</span>
              </label>
              <Input
                id={`${platform.id}-public-url`}
                value={publicVideoBaseUrl}
                onChange={(e) => setPublicVideoBaseUrl(e.target.value)}
                placeholder="https://cdn.yoursite.com/storage"
                aria-required="true"
              />
              <p className="text-[11px] text-txt-tertiary mt-1">
                Instagram Reels need a public HTTPS URL that maps to the storage folder
                Drevalis writes videos into. Without this, upload will fail.
              </p>
            </div>
          )}

          <div>
            <label
              htmlFor={`${platform.id}-refresh-token`}
              className="block text-xs font-medium text-txt-secondary mb-1"
            >
              Refresh Token{' '}
              <span className="text-txt-tertiary font-normal">(optional)</span>
            </label>
            <Input
              id={`${platform.id}-refresh-token`}
              type="password"
              value={refreshToken}
              onChange={(e) => setRefreshToken(e.target.value)}
              placeholder="Paste your refresh token..."
            />
          </div>

          {connectError && (
            <div
              className="flex items-center gap-2 text-sm text-error"
              role="alert"
              aria-live="polite"
            >
              <AlertCircle size={13} className="shrink-0" />
              {connectError}
            </div>
          )}

          <div className="flex justify-end gap-2 pt-1">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setFormOpen(false);
                setConnectError(null);
              }}
            >
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              loading={connecting}
              disabled={!accountName.trim() || !accessToken.trim()}
              onClick={() => void handleConnect()}
            >
              Connect {platform.name}
            </Button>
          </div>
        </div>
      )}

      {/* Setup wizard */}
      {platform.id === 'tiktok' && (
        <SocialConnectWizard
          open={wizardOpen}
          platform="tiktok"
          onClose={() => setWizardOpen(false)}
          onConnected={() => setWizardOpen(false)}
        />
      )}
    </Card>
  );
}
