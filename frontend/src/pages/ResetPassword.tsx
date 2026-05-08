import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { KeyRound, ShieldCheck } from 'lucide-react';
import { auth, formatError } from '@/lib/api';
import { Input } from '@/components/ui/Input';

/**
 * Password-reset page — reached via the link in the reset email.
 *
 * URL shape: /reset-password?token=<raw_token>
 *
 * Two-stage flow when TOTP 2FA is active:
 *
 * Stage 1 — new password form.  Backend returns either:
 *   { message: "password_reset_successful" }       → show success, redirect to /login.
 *   { stage: "totp_required", challenge: string }   → show TOTP input.
 *
 * Stage 2 — 6-digit TOTP code (or 16-char recovery code).
 *   POST /auth/login/totp with { challenge, code }  → redirect to / on success.
 *
 * Mounted outside LoginGate / LicenseGate so it is reachable without a
 * session cookie.
 */
export default function ResetPasswordPage() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token') ?? '';

  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  // TOTP second-factor state (mirrors Login.tsx TOTP stage).
  const [totpChallenge, setTotpChallenge] = useState<string | null>(null);
  const [totpCode, setTotpCode] = useState('');
  const [useRecovery, setUseRecovery] = useState(false);
  const [totpSubmitting, setTotpSubmitting] = useState(false);

  // Show an error immediately if the token is missing from the URL.
  const [missingToken] = useState(!token);

  // ── Stage 1: set new password ──────────────────────────────────────

  const submitPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    if (password !== confirm) {
      setError('Passwords do not match.');
      return;
    }
    if (password.length < 8) {
      setError('Password must be at least 8 characters.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const result = await auth.resetPassword(token, password);
      if ('stage' in result && result.stage === 'totp_required') {
        setTotpChallenge(result.challenge);
      } else {
        setDone(true);
        setTimeout(() => {
          window.location.href = '/login';
        }, 2500);
      }
    } catch (err) {
      setError(formatError(err) || 'Invalid or expired link. Request a new one.');
    } finally {
      setSubmitting(false);
    }
  };

  // ── Stage 2: TOTP code ─────────────────────────────────────────────

  const submitTotp = async (e: React.FormEvent) => {
    e.preventDefault();
    const code = totpCode.trim();
    if (!code || !totpChallenge) return;
    setTotpSubmitting(true);
    setError(null);
    try {
      await auth.loginTotp(totpChallenge, code);
      window.location.href = '/';
    } catch (err) {
      setError(formatError(err) || 'Invalid code. Try again.');
      setTotpCode('');
    } finally {
      setTotpSubmitting(false);
    }
  };

  // ── Missing token ──────────────────────────────────────────────────

  if (missingToken) {
    return (
      <div className="min-h-[100dvh] flex items-center justify-center bg-bg-base p-6">
        <div className="w-full max-w-sm bg-bg-elevated/80 border border-white/[0.06] rounded-lg p-8 shadow-lg backdrop-blur-sm text-center">
          <p className="text-sm text-error mb-4">
            No reset token found in this URL. Please request a new reset link.
          </p>
          <a href="/login" className="text-accent text-sm underline underline-offset-2">
            Back to sign in
          </a>
        </div>
      </div>
    );
  }

  // ── Success screen ─────────────────────────────────────────────────

  if (done) {
    return (
      <div className="min-h-[100dvh] flex items-center justify-center bg-bg-base p-6">
        <div className="w-full max-w-sm bg-bg-elevated/80 border border-white/[0.06] rounded-lg p-8 shadow-lg backdrop-blur-sm text-center">
          <p className="text-sm text-txt-primary mb-2">Password updated.</p>
          <p className="text-xs text-txt-secondary">Redirecting to sign in…</p>
        </div>
      </div>
    );
  }

  // ── TOTP stage ─────────────────────────────────────────────────────

  if (totpChallenge) {
    return (
      <div className="min-h-[100dvh] flex items-center justify-center bg-bg-base p-6">
        <div className="w-full max-w-sm bg-bg-elevated/80 border border-white/[0.06] rounded-lg p-8 shadow-lg backdrop-blur-sm">
          <div className="flex items-center justify-center w-12 h-12 rounded-full bg-accent/15 border border-accent/30 mx-auto mb-4">
            <ShieldCheck className="text-accent" size={20} />
          </div>
          <h1 className="text-xl font-semibold text-center text-txt-primary mb-1">
            Two-factor verification
          </h1>
          <p className="text-xs text-center text-txt-secondary mb-6">
            {useRecovery
              ? 'Enter one of your 16-character recovery codes.'
              : 'Enter the 6-digit code from your authenticator app.'}
          </p>

          <form onSubmit={submitTotp} className="space-y-4">
            <Input
              label={useRecovery ? 'Recovery code' : 'Authentication code'}
              type="text"
              inputMode={useRecovery ? 'text' : 'numeric'}
              autoComplete="one-time-code"
              required
              autoFocus
              value={totpCode}
              maxLength={useRecovery ? 16 : 6}
              placeholder={useRecovery ? 'abcdef0123456789' : '123456'}
              onChange={(e) => setTotpCode(e.target.value)}
            />

            {error && (
              <div className="p-2 rounded border border-error/30 bg-error/10 text-xs text-error" role="alert">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={totpSubmitting}
              className="w-full rounded-md bg-gradient-to-r from-accent to-accent-hover text-bg-base font-semibold py-2.5 text-sm disabled:opacity-50"
            >
              {totpSubmitting ? 'Verifying…' : 'Verify'}
            </button>
          </form>

          <div className="flex items-center justify-between mt-4">
            <button
              type="button"
              onClick={() => { setUseRecovery(!useRecovery); setTotpCode(''); setError(null); }}
              className="text-[11px] text-txt-muted hover:text-txt-secondary underline underline-offset-2"
            >
              {useRecovery ? 'Use authenticator app instead' : 'Use a recovery code instead'}
            </button>
            <a
              href="/login"
              className="text-[11px] text-txt-muted hover:text-txt-secondary underline underline-offset-2"
            >
              Back to sign in
            </a>
          </div>
        </div>
      </div>
    );
  }

  // ── Stage 1: set new password ──────────────────────────────────────

  return (
    <div className="min-h-[100dvh] flex items-center justify-center bg-bg-base p-6">
      <div className="w-full max-w-sm bg-bg-elevated/80 border border-white/[0.06] rounded-lg p-8 shadow-lg backdrop-blur-sm">
        <div className="flex items-center justify-center w-12 h-12 rounded-full bg-accent/15 border border-accent/30 mx-auto mb-4">
          <KeyRound className="text-accent" size={20} />
        </div>
        <h1 className="text-xl font-semibold text-center text-txt-primary mb-1">
          Set new password
        </h1>
        <p className="text-xs text-center text-txt-secondary mb-6">
          Choose a strong password of at least 8 characters.
        </p>

        <form onSubmit={submitPassword} className="space-y-4">
          <Input
            label="New password"
            type="password"
            autoComplete="new-password"
            required
            autoFocus
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <Input
            label="Confirm password"
            type="password"
            autoComplete="new-password"
            required
            minLength={8}
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
          />

          {error && (
            <div className="p-2 rounded border border-error/30 bg-error/10 text-xs text-error" role="alert">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-md bg-gradient-to-r from-accent to-accent-hover text-bg-base font-semibold py-2.5 text-sm disabled:opacity-50"
          >
            {submitting ? 'Saving…' : 'Set password'}
          </button>
        </form>

        <p className="text-center mt-4">
          <a href="/login" className="text-[11px] text-txt-muted hover:text-txt-secondary underline underline-offset-2">
            Back to sign in
          </a>
        </p>
      </div>
    </div>
  );
}
