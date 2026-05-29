import { useState } from 'react';
import {
  AlertCircle,
  ChevronUp,
  Plus,
  Link2,
  Unlink,
} from 'lucide-react';
import { Trans, useTranslation } from 'react-i18next';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Badge } from '@/components/ui/Badge';
import { ConfirmDangerousDialog } from '@/components/ui/ConfirmDangerousDialog';
import { SocialConnectWizard } from '@/components/social/SocialConnectWizard';
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
  const { t } = useTranslation();
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
      // Always go through the wizard for OAuth platforms — same fix as
      // YouTubeSection. Sending the whole webview to the provider via
      // ``window.location.href`` strands the user on the backend's JSON
      // callback response and breaks the "add another account" flow.
      // The wizard opens the OAuth URL in the system browser and polls
      // for the new connection instead.
      if (platform.id === 'tiktok') {
        setWizardOpen(true);
      }
      return;
    }

    if (!accountName.trim() || !accessToken.trim()) return;
    if (needsAccountId && !accountId.trim()) {
      setConnectError(
        platform.id === 'facebook'
          ? t('settings.social.platform.errors.facebookNeedsPageId')
          : t('settings.social.platform.errors.instagramNeedsAccountId'),
      );
      return;
    }
    if (needsPublicUrl && !publicVideoBaseUrl.trim()) {
      setConnectError(t('settings.social.platform.errors.instagramNeedsPublicUrl'));
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
      setConnectError(err instanceof Error ? err.message : t('settings.social.platform.errors.connectFailed'));
    } finally {
      setConnecting(false);
    }
  };

  const [disconnectConfirmOpen, setDisconnectConfirmOpen] = useState(false);

  const handleDisconnect = async () => {
    if (!connectedAccount) return;
    setDisconnecting(true);
    try {
      await onDisconnect(connectedAccount.id);
      setDisconnectConfirmOpen(false);
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
              <p className="text-xs text-txt-tertiary">{t('settings.social.platform.notConnected')}</p>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {isConnected ? (
            <>
              <Badge variant="success" dot>
                {t('settings.social.platform.connected')}
              </Badge>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setDisconnectConfirmOpen(true)}
                className="text-txt-tertiary hover:text-error"
                aria-label={t('settings.social.platform.disconnectAria', { platform: platform.name })}
              >
                <Unlink size={13} />
                {t('settings.social.platform.disconnect')}
              </Button>
            </>
          ) : (
            <>
              <Badge variant="neutral">{t('settings.social.platform.notConnected')}</Badge>
              {platform.id === 'tiktok' && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setWizardOpen(true)}
                  title={t('settings.social.platform.setupWizardTitle')}
                >
                  {t('settings.social.platform.setupWizard')}
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
                    {t('settings.social.platform.connectPlatform', { platform: platform.name })}
                  </>
                ) : formOpen ? (
                  <>
                    <ChevronUp size={13} />
                    {t('settings.social.platform.cancel')}
                  </>
                ) : (
                  <>
                    <Plus size={13} />
                    {t('settings.social.platform.connectGeneric')}
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
          aria-label={t('settings.social.platform.connectFormAria', { platform: platform.name })}
        >
          <div>
            <label
              htmlFor={`${platform.id}-account-name`}
              className="block text-xs font-medium text-txt-secondary mb-1"
            >
              {t('settings.social.platform.accountName')}
            </label>
            <Input
              id={`${platform.id}-account-name`}
              value={accountName}
              onChange={(e) => setAccountName(e.target.value)}
              placeholder={t('settings.social.platform.accountNamePlaceholder')}
              aria-required="true"
            />
          </div>

          {needsAccountId && (
            <div>
              <label
                htmlFor={`${platform.id}-account-id`}
                className="block text-xs font-medium text-txt-secondary mb-1"
              >
                {platform.id === 'facebook'
                  ? t('settings.social.platform.facebookPageId')
                  : t('settings.social.platform.instagramAccountId')}
                <span className="text-error ml-1">*</span>
              </label>
              <Input
                id={`${platform.id}-account-id`}
                value={accountId}
                onChange={(e) => setAccountId(e.target.value)}
                placeholder={
                  platform.id === 'facebook'
                    ? t('settings.social.platform.facebookPageIdPlaceholder')
                    : t('settings.social.platform.instagramAccountIdPlaceholder')
                }
                aria-required="true"
              />
              <p className="text-[11px] text-txt-tertiary mt-1">
                {platform.id === 'facebook'
                  ? t('settings.social.platform.facebookPageIdHint')
                  : t('settings.social.platform.instagramAccountIdHint')}
              </p>
            </div>
          )}

          <div>
            <label
              htmlFor={`${platform.id}-access-token`}
              className="block text-xs font-medium text-txt-secondary mb-1"
            >
              {platform.id === 'facebook'
                ? t('settings.social.platform.pageAccessToken')
                : t('settings.social.platform.apiAccessToken')}
              <span className="text-error ml-1">*</span>
            </label>
            <Input
              id={`${platform.id}-access-token`}
              type="password"
              value={accessToken}
              onChange={(e) => setAccessToken(e.target.value)}
              placeholder={
                platform.id === 'facebook'
                  ? t('settings.social.platform.facebookTokenPlaceholder')
                  : t('settings.social.platform.tokenPlaceholder')
              }
              aria-required="true"
            />
            {platform.id === 'facebook' && (
              <p className="text-[11px] text-txt-tertiary mt-1">
                <Trans
                  i18nKey="settings.social.platform.facebookTokenHint"
                  components={{ 1: <code /> }}
                />
              </p>
            )}
          </div>

          {needsPublicUrl && (
            <div>
              <label
                htmlFor={`${platform.id}-public-url`}
                className="block text-xs font-medium text-txt-secondary mb-1"
              >
                {t('settings.social.platform.publicVideoBaseUrl')}
                <span className="text-error ml-1">*</span>
              </label>
              <Input
                id={`${platform.id}-public-url`}
                value={publicVideoBaseUrl}
                onChange={(e) => setPublicVideoBaseUrl(e.target.value)}
                placeholder={t('settings.social.platform.publicVideoBaseUrlPlaceholder')}
                aria-required="true"
              />
              <p className="text-[11px] text-txt-tertiary mt-1">
                {t('settings.social.platform.publicVideoBaseUrlHint')}
              </p>
            </div>
          )}

          <div>
            <label
              htmlFor={`${platform.id}-refresh-token`}
              className="block text-xs font-medium text-txt-secondary mb-1"
            >
              {t('settings.social.platform.refreshToken')}{' '}
              <span className="text-txt-tertiary font-normal">{t('settings.social.platform.refreshTokenOptional')}</span>
            </label>
            <Input
              id={`${platform.id}-refresh-token`}
              type="password"
              value={refreshToken}
              onChange={(e) => setRefreshToken(e.target.value)}
              placeholder={t('settings.social.platform.refreshTokenPlaceholder')}
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
              {t('settings.social.platform.cancel')}
            </Button>
            <Button
              variant="primary"
              size="sm"
              loading={connecting}
              disabled={!accountName.trim() || !accessToken.trim()}
              onClick={() => void handleConnect()}
            >
              {t('settings.social.platform.connectPlatform', { platform: platform.name })}
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

      {/* Disconnect — typed-confirm (Phase 4). The confirm word is the
          platform's short id so users must scope what they're disconnecting
          per-platform rather than blast through a generic "DELETE". */}
      {isConnected && (
        <ConfirmDangerousDialog
          open={disconnectConfirmOpen}
          onClose={() => setDisconnectConfirmOpen(false)}
          onConfirm={() => void handleDisconnect()}
          title={t('settings.social.platform.disconnectDialog.title', { platform: platform.name })}
          warning={
            <Trans
              i18nKey="settings.social.platform.disconnectDialog.warning"
              values={{
                account: connectedAccount?.account_name
                  ? `@${connectedAccount.account_name}`
                  : platform.name,
              }}
              components={{ 1: <strong className="text-txt-primary" /> }}
            />
          }
          consequences={
            (t('settings.social.platform.disconnectDialog.consequences', {
              returnObjects: true,
              platform: platform.name,
            }) as string[])
          }
          confirmWord={platform.id.toUpperCase()}
          confirmLabel={t('settings.social.platform.disconnectDialog.confirmLabel', { platform: platform.name })}
          loading={disconnecting}
        />
      )}
    </Card>
  );
}
