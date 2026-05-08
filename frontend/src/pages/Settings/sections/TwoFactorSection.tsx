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
      setError(formatError(err) || 'Enrolment failed. Try again.');
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
      toast.success('Two-factor authentication enabled.');
      // Refresh auth context so user.totp_enabled reflects the new state.
      window.dispatchEvent(new CustomEvent('auth:refresh'));
    } catch (err) {
      setError(formatError(err) || 'Invalid code. Check your authenticator app and try again.');
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
      toast.success('Two-factor authentication disabled.');
      window.dispatchEvent(new CustomEvent('auth:refresh'));
    } catch (err) {
      setError(formatError(err) || 'Incorrect password.');
    } finally {
      setLoading(false);
    }
  };

  const copyToClipboard = (text: string, label: string) => {
    navigator.clipboard.writeText(text).then(
      () => toast.success(`${label} copied.`),
      () => toast.error('Copy failed — please copy manually.'),
    );
  };

  // ── Render helpers ──────────────────────────────────────────────────

  const renderIdle = () => (
    <div className="space-y-3">
      <p className="text-sm text-txt-secondary">
        Two-factor authentication adds a second layer of protection. After enabling it,
        you will be prompted for a code from your authenticator app each time you sign in.
      </p>
      {error && <ErrorBanner message={error} />}
      <Button onClick={startEnroll} disabled={loading} variant="primary" size="sm">
        {loading ? 'Setting up…' : 'Enable 2FA'}
      </Button>
    </div>
  );

  const renderConfirming = () => {
    if (!enrollData) return null;
    const { secret_base32, otpauth_uri, recovery_codes } = enrollData;

    return (
      <form onSubmit={confirmEnroll} className="space-y-5">
        <p className="text-sm text-txt-secondary">
          Scan the link below with your authenticator app (Google Authenticator, Authy, 1Password,
          etc.), or manually enter the secret key.
        </p>

        {/* otpauth URI — open in authenticator app */}
        <div className="space-y-1">
          <p className="text-xs font-medium text-txt-secondary">Open in authenticator</p>
          <div className="flex gap-2 items-center">
            <a
              href={otpauth_uri}
              className="text-accent text-xs underline underline-offset-2 break-all"
              title="Open in authenticator app"
            >
              {otpauth_uri.slice(0, 60)}…
            </a>
            <button
              type="button"
              onClick={() => copyToClipboard(otpauth_uri, 'URI')}
              className="shrink-0 text-txt-muted hover:text-txt-secondary"
              title="Copy otpauth URI"
            >
              <Copy size={14} />
            </button>
          </div>
        </div>

        {/* Manual secret entry */}
        <div className="space-y-1">
          <p className="text-xs font-medium text-txt-secondary">Or enter this secret manually</p>
          <div className="flex gap-2 items-center">
            <code className="text-xs font-mono bg-bg-base px-2 py-1 rounded border border-white/10 tracking-widest select-all">
              {secret_base32}
            </code>
            <button
              type="button"
              onClick={() => copyToClipboard(secret_base32, 'Secret')}
              className="shrink-0 text-txt-muted hover:text-txt-secondary"
              title="Copy secret"
            >
              <Copy size={14} />
            </button>
          </div>
        </div>

        {/* Recovery codes — shown once */}
        <div className="space-y-1">
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium text-txt-secondary">
              Recovery codes
              <span className="ml-1 text-warning text-[10px]">(save these now — shown once)</span>
            </p>
            <button
              type="button"
              onClick={() => copyToClipboard(recovery_codes.join('\n'), 'Recovery codes')}
              className="text-txt-muted hover:text-txt-secondary"
              title="Copy all recovery codes"
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
            Store these in a password manager. Each code can be used once if you lose access to
            your authenticator app.
          </p>
        </div>

        {/* Confirm code */}
        <div className="space-y-2">
          <Input
            label="Enter the 6-digit code from your app to activate"
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
            {loading ? 'Activating…' : 'Activate 2FA'}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => { setStage('idle'); setEnrollData(null); setError(null); }}
          >
            Cancel
          </Button>
        </div>
      </form>
    );
  };

  const renderActive = () => (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-success">
        <CheckCircle2 size={16} />
        <span className="text-sm font-medium">Two-factor authentication is active</span>
      </div>
      <p className="text-sm text-txt-secondary">
        Your account is protected by a TOTP authenticator app. You will be prompted for a code
        on every sign-in.
      </p>
      <Button onClick={startDisable} variant="ghost" size="sm">
        <ShieldOff size={14} className="mr-1.5" />
        Disable 2FA
      </Button>
    </div>
  );

  const renderDisabling = () => (
    <form onSubmit={confirmDisable} className="space-y-4">
      <p className="text-sm text-txt-secondary">
        To disable two-factor authentication, confirm your account password.
      </p>
      <Input
        label="Current password"
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
          {loading ? 'Disabling…' : 'Disable 2FA'}
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => { setStage('active'); setError(null); }}
        >
          Cancel
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
        <h2 className="text-sm font-semibold text-txt-primary">Two-factor authentication</h2>
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
