/**
 * TwoFactorSection — TOTP 2FA management in Settings > Account.
 *
 * State machine:
 *
 *   idle (no 2FA)
 *     └─ "Enable 2FA" → enrolling
 *          └─ POST /2fa/enroll → show QR URI + recovery codes + confirm input
 *               └─ "Activate" (6-digit code) → POST /2fa/confirm → active
 *
 *   active (2FA on)
 *     └─ "Disable 2FA" → disabling → password prompt
 *          └─ POST /2fa/disable → idle
 *
 * QR rendering: we do not add a QR library to the bundle. Instead we:
 *   1. Show the raw secret as a copyable text field (for manual entry).
 *   2. Show the otpauth:// URI as a clickable link (most OS/browser
 *      combinations will open the registered authenticator app).
 *   3. Show a "Copy URI" button as a fallback for desktop.
 *
 * This keeps the bundle cost at zero while covering the common cases.
 */

import { useState } from 'react';
import { Copy, ShieldCheck, ShieldOff, ShieldAlert, CheckCircle2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { useToast } from '@/components/ui/Toast';
import { auth as authApi, formatError, type TotpEnrollResponse } from '@/lib/api';
import { useAuth } from '@/lib/useAuth';

type Stage =
  | 'idle'          // 2FA not enrolled
  | 'enrolling'     // waiting for POST /enroll to return
  | 'confirming'    // secret generated, waiting for user to verify code
  | 'disabling'     // waiting for user to enter password
  | 'active';       // 2FA confirmed and active

export function TwoFactorSection() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const { toast } = useToast();

  const initialStage: Stage = user?.totp_enabled ? 'active' : 'idle';
  const [stage, setStage] = useState<Stage>(initialStage);
  const [enrollData, setEnrollData] = useState<TotpEnrollResponse | null>(null);
  const [confirmCode, setConfirmCode] = useState('');
  const [disablePassword, setDisablePassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ── Actions ─────────────────────────────────────────────────────────

  const startEnroll = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await authApi.enrollTotp();
      setEnrollData(data);
      setStage('confirming');
    } catch (err) {
      setError(formatError(err) || t('settings.twoFactor.enrollmentFailed'));
    } finally {
      setLoading(false);
    }
  };

  const confirmEnroll = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!confirmCode.trim()) return;
    setLoading(true);
    setError(null);
    try {
      await authApi.confirmTotp(confirmCode.trim());
      setStage('active');
      setEnrollData(null);
      setConfirmCode('');
      toast.success(t('settings.twoFactor.enabledToast'));
      // Refresh auth context so user.totp_enabled reflects the new state.
      window.dispatchEvent(new CustomEvent('auth:refresh'));
    } catch (err) {
      setError(formatError(err) || t('settings.twoFactor.invalidCode'));
    } finally {
      setLoading(false);
    }
  };

  const startDisable = () => {
    setDisablePassword('');
    setError(null);
    setStage('disabling');
  };

  const confirmDisable = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!disablePassword) return;
    setLoading(true);
    setError(null);
    try {
      await authApi.disableTotp(disablePassword);
      setStage('idle');
      setDisablePassword('');
      toast.success(t('settings.twoFactor.disabledToast'));
      window.dispatchEvent(new CustomEvent('auth:refresh'));
    } catch (err) {
      setError(formatError(err) || t('settings.twoFactor.incorrectPassword'));
    } finally {
      setLoading(false);
    }
  };

  const copyToClipboard = (text: string, label: string) => {
    navigator.clipboard.writeText(text).then(
      () => toast.success(t('settings.twoFactor.copiedToast', { label })),
      () => toast.error(t('settings.twoFactor.copyFailed')),
    );
  };

  // ── Render helpers ──────────────────────────────────────────────────

  const renderIdle = () => (
    <div className="space-y-3">
      <p className="text-sm text-txt-secondary">
        {t('settings.twoFactor.idle.intro')}
      </p>
      {error && <ErrorBanner message={error} />}
      <Button onClick={startEnroll} disabled={loading} variant="primary" size="sm">
        {loading ? t('settings.twoFactor.idle.settingUp') : t('settings.twoFactor.idle.enable')}
      </Button>
    </div>
  );

  const renderConfirming = () => {
    if (!enrollData) return null;
    const { secret_base32, otpauth_uri, recovery_codes } = enrollData;

    return (
      <form onSubmit={confirmEnroll} className="space-y-5">
        <p className="text-sm text-txt-secondary">
          {t('settings.twoFactor.confirming.intro')}
        </p>

        {/* otpauth URI — open in authenticator app */}
        <div className="space-y-1">
          <p className="text-xs font-medium text-txt-secondary">{t('settings.twoFactor.confirming.openInAuthenticator')}</p>
          <div className="flex gap-2 items-center">
            <a
              href={otpauth_uri}
              className="text-accent text-xs underline underline-offset-2 break-all"
              title={t('settings.twoFactor.confirming.openInAuthenticatorTitle')}
            >
              {otpauth_uri.slice(0, 60)}…
            </a>
            <button
              type="button"
              onClick={() => copyToClipboard(otpauth_uri, t('settings.twoFactor.labels.uri'))}
              className="shrink-0 text-txt-muted hover:text-txt-secondary"
              title={t('settings.twoFactor.confirming.copyUriTitle')}
            >
              <Copy size={14} />
            </button>
          </div>
        </div>

        {/* Manual secret entry */}
        <div className="space-y-1">
          <p className="text-xs font-medium text-txt-secondary">{t('settings.twoFactor.confirming.manualSecret')}</p>
          <div className="flex gap-2 items-center">
            <code className="text-xs font-mono bg-bg-base px-2 py-1 rounded border border-white/10 tracking-widest select-all">
              {secret_base32}
            </code>
            <button
              type="button"
              onClick={() => copyToClipboard(secret_base32, t('settings.twoFactor.labels.secret'))}
              className="shrink-0 text-txt-muted hover:text-txt-secondary"
              title={t('settings.twoFactor.confirming.copySecretTitle')}
            >
              <Copy size={14} />
            </button>
          </div>
        </div>

        {/* Recovery codes — shown once */}
        <div className="space-y-1">
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium text-txt-secondary">
              {t('settings.twoFactor.confirming.recoveryCodes')}
              <span className="ml-1 text-warning text-[10px]">{t('settings.twoFactor.confirming.recoveryCodesNote')}</span>
            </p>
            <button
              type="button"
              onClick={() => copyToClipboard(recovery_codes.join('\n'), t('settings.twoFactor.labels.recoveryCodes'))}
              className="text-txt-muted hover:text-txt-secondary"
              title={t('settings.twoFactor.confirming.copyRecoveryTitle')}
            >
              <Copy size={14} />
            </button>
          </div>
          <div className="grid grid-cols-2 gap-1 bg-bg-base border border-white/10 rounded p-3">
            {recovery_codes.map((code) => (
              <code key={code} className="text-xs font-mono text-txt-primary tracking-wider">
                {code}
              </code>
            ))}
          </div>
          <p className="text-[11px] text-txt-muted">
            {t('settings.twoFactor.confirming.storeHint')}
          </p>
        </div>

        {/* Confirm code */}
        <div className="space-y-2">
          <Input
            label={t('settings.twoFactor.confirming.codeLabel')}
            type="text"
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            placeholder="123456"
            value={confirmCode}
            onChange={(e) => setConfirmCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
          />
          {error && <ErrorBanner message={error} />}
        </div>

        <div className="flex gap-2">
          <Button
            type="submit"
            disabled={loading || confirmCode.length !== 6}
            variant="primary"
            size="sm"
          >
            {loading ? t('settings.twoFactor.confirming.activating') : t('settings.twoFactor.confirming.activate')}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => { setStage('idle'); setEnrollData(null); setError(null); }}
          >
            {t('settings.twoFactor.confirming.cancel')}
          </Button>
        </div>
      </form>
    );
  };

  const renderActive = () => (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-success">
        <CheckCircle2 size={16} />
        <span className="text-sm font-medium">{t('settings.twoFactor.active.status')}</span>
      </div>
      <p className="text-sm text-txt-secondary">
        {t('settings.twoFactor.active.intro')}
      </p>
      <Button onClick={startDisable} variant="ghost" size="sm">
        <ShieldOff size={14} className="mr-1.5" />
        {t('settings.twoFactor.active.disable')}
      </Button>
    </div>
  );

  const renderDisabling = () => (
    <form onSubmit={confirmDisable} className="space-y-4">
      <p className="text-sm text-txt-secondary">
        {t('settings.twoFactor.disabling.intro')}
      </p>
      <Input
        label={t('settings.twoFactor.disabling.currentPassword')}
        type="password"
        autoComplete="current-password"
        required
        autoFocus
        value={disablePassword}
        onChange={(e) => setDisablePassword(e.target.value)}
      />
      {error && <ErrorBanner message={error} />}
      <div className="flex gap-2">
        <Button type="submit" disabled={loading || !disablePassword} variant="destructive" size="sm">
          {loading ? t('settings.twoFactor.disabling.disabling') : t('settings.twoFactor.disabling.disable')}
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => { setStage('active'); setError(null); }}
        >
          {t('settings.twoFactor.disabling.cancel')}
        </Button>
      </div>
    </form>
  );

  // ── Card shell ──────────────────────────────────────────────────────

  const icon = stage === 'active'
    ? <ShieldCheck size={18} className="text-success" />
    : stage === 'disabling'
    ? <ShieldAlert size={18} className="text-warning" />
    : <ShieldCheck size={18} className="text-txt-muted" />;

  return (
    <Card>
      <div className="flex items-center gap-2 mb-4">
        {icon}
        <h2 className="text-sm font-semibold text-txt-primary">{t('settings.twoFactor.heading')}</h2>
      </div>

      {stage === 'idle' && renderIdle()}
      {(stage === 'enrolling' || stage === 'confirming') && renderConfirming()}
      {stage === 'active' && renderActive()}
      {stage === 'disabling' && renderDisabling()}
    </Card>
  );
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="p-2 rounded border border-error/30 bg-error/10 text-xs text-error" role="alert">
      {message}
    </div>
  );
}
