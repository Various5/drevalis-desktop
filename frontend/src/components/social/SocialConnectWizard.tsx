import { useEffect, useState } from 'react';
import {
  CheckCircle2,
  AlertTriangle,
  ExternalLink,
  Loader2,
  Eye,
  EyeOff,
  Copy,
  ChevronLeft,
  ChevronRight,
  Sparkles,
  Youtube,
  Music2,
} from 'lucide-react';
import { Dialog, DialogFooter } from '@/components/ui/Dialog';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Badge } from '@/components/ui/Badge';
import { useToast } from '@/components/ui/Toast';
import {
  apiKeys as apiKeysApi,
  youtube as youtubeApi,
  social as socialApi,
} from '@/lib/api';
import { openExternal } from '@/lib/tauri';

// SocialConnectWizard
//
// Walks the user through connecting an OAuth-driven social platform
// (YouTube or TikTok) end-to-end. The platforms each need:
//   1. App credentials from the provider's developer portal
//      (client_id + client_secret + sometimes a redirect URI).
//   2. Those credentials persisted in the api_key_store table so the
//      backend can build the OAuth authorize URL.
//   3. The user redirected to the provider for consent.
//   4. The callback round-trip; we verify the connection landed.
//
// The previous flow assumed the user could find the right env-var
// names and paste them into Settings → API Keys with no guidance.
// This wizard removes that guesswork: explains *why* each value is
// needed, links to exactly where to get it, stores it, and runs the
// auth round-trip without leaving the page (popup window).

export type SocialPlatform = 'youtube' | 'tiktok';

interface PlatformSpec {
  id: SocialPlatform;
  label: string;
  icon: typeof Youtube;
  // Where the user gets credentials.
  portalUrl: string;
  portalLabel: string;
  // Step-by-step instructions for getting credentials.
  setupSteps: string[];
  // Names of api_key_store rows the wizard will write.
  credentialKeys: Array<{
    keyName: string;
    label: string;
    placeholder: string;
    helper: string;
    sensitive: boolean; // hide by default
  }>;
  // Default redirect URI to display (read-only) so the user copies
  // it into the provider portal verbatim.
  defaultRedirectUri: string;
  // Scopes shown so the user knows what they're authorizing.
  scopes: string[];
  // Endpoint to call to mint the consent URL after credentials saved.
  fetchAuthUrl: () => Promise<{ auth_url: string }>;
  // Snapshot the current connected-channel "fingerprint" before kicking
  // off auth. Used to detect *new* connections — boolean "connected"
  // alone is unreliable for second-channel onboarding because the
  // platform already reports connected=true from a previous channel.
  snapshotConnections: () => Promise<string>;
  // Returns true if connections have grown / changed vs the snapshot.
  hasNewConnection: (snapshot: string) => Promise<boolean>;
  // Returns true if at least one credential is already saved server-side.
  // When true the wizard skips the "intro" + "credentials" steps and
  // goes straight to authorize.
  credentialsAlreadyConfigured: () => Promise<boolean>;
}

const SPECS: Record<SocialPlatform, PlatformSpec> = {
  youtube: {
    id: 'youtube',
    label: 'YouTube',
    icon: Youtube,
    portalUrl: 'https://console.cloud.google.com/apis/credentials',
    portalLabel: 'Google Cloud Console — Credentials',
    setupSteps: [
      'Sign in to the Google Cloud Console with the account that owns your YouTube channel.',
      'Create a new project (or pick an existing one).',
      'Enable the "YouTube Data API v3" under APIs & Services → Library.',
      'In APIs & Services → OAuth consent screen, configure an "External" app and add yourself as a test user.',
      'In APIs & Services → Credentials, click "Create credentials" → "OAuth client ID" → "Web application".',
      'Add the redirect URI shown below to "Authorized redirect URIs", then copy the Client ID + Client Secret here.',
    ],
    credentialKeys: [
      {
        keyName: 'youtube_client_id',
        label: 'Client ID',
        placeholder: '123456789-abc...apps.googleusercontent.com',
        helper: 'Looks like a long string ending in .apps.googleusercontent.com',
        sensitive: false,
      },
      {
        keyName: 'youtube_client_secret',
        label: 'Client Secret',
        placeholder: 'GOCSPX-...',
        helper: 'Stored encrypted at rest with Fernet. Never logged.',
        sensitive: true,
      },
    ],
    defaultRedirectUri:
      typeof window !== 'undefined'
        ? `${window.location.origin}/api/v1/youtube/callback`
        : '/api/v1/youtube/callback',
    scopes: [
      'youtube.upload — publish videos',
      'youtube.readonly — read your channel + analytics',
    ],
    fetchAuthUrl: () => youtubeApi.getAuthUrl(),
    snapshotConnections: async () => {
      try {
        const channels = await youtubeApi.listChannels();
        return channels.map((c) => c.id).sort().join(',');
      } catch {
        return '';
      }
    },
    hasNewConnection: async (snapshot: string) => {
      try {
        const channels = await youtubeApi.listChannels();
        const current = channels.map((c) => c.id).sort().join(',');
        return current !== snapshot && channels.length > 0;
      } catch {
        return false;
      }
    },
    credentialsAlreadyConfigured: async () => {
      try {
        const integrations = await apiKeysApi.integrations();
        return Boolean(integrations.youtube?.configured);
      } catch {
        return false;
      }
    },
  },
  tiktok: {
    id: 'tiktok',
    label: 'TikTok',
    icon: Music2,
    portalUrl: 'https://developers.tiktok.com/apps',
    portalLabel: 'TikTok for Developers — My Apps',
    setupSteps: [
      'Sign in at developers.tiktok.com with your TikTok account.',
      'Create a new app (or open an existing one) under "Manage apps".',
      'Add the "Login Kit" and "Content Posting API" products to the app.',
      'Under Login Kit settings, add the redirect URI shown below to the allowed redirect URIs.',
      'Request the scopes: user.info.basic, video.publish, video.upload.',
      'Copy the Client Key + Client Secret from the app overview into the fields here.',
    ],
    credentialKeys: [
      {
        keyName: 'tiktok_client_key',
        label: 'Client Key',
        placeholder: 'aw...',
        helper: 'TikTok labels this "Client Key" (not "Client ID").',
        sensitive: false,
      },
      {
        keyName: 'tiktok_client_secret',
        label: 'Client Secret',
        placeholder: 'Long alphanumeric string',
        helper: 'Stored encrypted at rest with Fernet. Never logged.',
        sensitive: true,
      },
    ],
    defaultRedirectUri:
      typeof window !== 'undefined'
        ? `${window.location.origin}/api/v1/social/tiktok/callback`
        : '/api/v1/social/tiktok/callback',
    scopes: [
      'user.info.basic — your handle + display name',
      'video.publish — post videos to your account',
      'video.upload — upload video files',
    ],
    fetchAuthUrl: async () => {
      const r = await socialApi.tiktokAuthUrl();
      return { auth_url: r.auth_url };
    },
    snapshotConnections: async () => {
      try {
        const r = await socialApi.tiktokStatus();
        return JSON.stringify({ connected: Boolean(r.connected) });
      } catch {
        return '';
      }
    },
    hasNewConnection: async (snapshot: string) => {
      try {
        const r = await socialApi.tiktokStatus();
        const current = JSON.stringify({ connected: Boolean(r.connected) });
        return Boolean(r.connected) && current !== snapshot;
      } catch {
        return false;
      }
    },
    credentialsAlreadyConfigured: async () => {
      try {
        const integrations = await apiKeysApi.integrations();
        return Boolean(integrations.tiktok?.configured);
      } catch {
        return false;
      }
    },
  },
};

interface Props {
  open: boolean;
  platform: SocialPlatform;
  onClose: () => void;
  /** Called once the wizard confirms the connection landed. */
  onConnected?: () => void;
}

type Step = 'intro' | 'credentials' | 'authorize' | 'verify';

export function SocialConnectWizard({
  open,
  platform,
  onClose,
  onConnected,
}: Props) {
  const spec = SPECS[platform];
  const { toast } = useToast();
  const [step, setStep] = useState<Step>('intro');
  const [creds, setCreds] = useState<Record<string, string>>({});
  const [revealed, setRevealed] = useState<Record<string, boolean>>({});
  const [savingCreds, setSavingCreds] = useState(false);
  const [authUrl, setAuthUrl] = useState<string | null>(null);
  const [authUrlError, setAuthUrlError] = useState<string | null>(null);
  const [polling, setPolling] = useState(false);
  const [verifyError, setVerifyError] = useState<string | null>(null);

  // Reset state every time the wizard is reopened. If credentials are
  // already configured we skip the intro + credentials steps and jump
  // straight to authorize — useful when adding a second channel: the
  // user shouldn't be made to re-paste their Google client_id every
  // time they want to add another channel to the same install.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    (async () => {
      setStep('intro');
      setCreds({});
      setRevealed({});
      setAuthUrl(null);
      setAuthUrlError(null);
      setVerifyError(null);
      setPolling(false);

      const alreadyConfigured = await spec.credentialsAlreadyConfigured();
      if (cancelled) return;
      if (!alreadyConfigured) return;

      // Mint the auth URL straight away so the authorize step is ready.
      try {
        const r = await spec.fetchAuthUrl();
        if (cancelled) return;
        setAuthUrl(r.auth_url);
        setStep('authorize');
      } catch (err) {
        if (cancelled) return;
        const detail =
          (err as { detail?: unknown })?.detail ??
          (err as { message?: string })?.message ??
          'Could not request a new authorization URL.';
        setAuthUrlError(typeof detail === 'string' ? detail : JSON.stringify(detail));
        setStep('credentials');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, platform, spec]);

  const copyRedirect = async () => {
    try {
      await navigator.clipboard.writeText(spec.defaultRedirectUri);
      toast.success('Redirect URI copied');
    } catch {
      toast.error('Copy failed');
    }
  };

  const allCredsFilled = spec.credentialKeys.every(
    (k) => (creds[k.keyName] ?? '').trim().length > 0,
  );

  const handleSaveCreds = async () => {
    if (!allCredsFilled) return;
    setSavingCreds(true);
    setAuthUrlError(null);
    try {
      // Persist each credential. The backend stores them encrypted
      // (Fernet) in api_key_store, then both the YouTube and TikTok
      // OAuth handlers will read from there in addition to env vars.
      for (const k of spec.credentialKeys) {
        await apiKeysApi.store(k.keyName, creds[k.keyName]!.trim());
      }
      toast.success(`${spec.label} credentials saved`);
      // Immediately try to fetch the auth URL — that proves the
      // backend can build a valid OAuth request with the new keys.
      const r = await spec.fetchAuthUrl();
      setAuthUrl(r.auth_url);
      setStep('authorize');
    } catch (err: unknown) {
      const detail =
        (err as { detail?: unknown })?.detail ??
        (err as { message?: string })?.message ??
        'Could not validate the credentials.';
      const msg = typeof detail === 'string' ? detail : JSON.stringify(detail);
      setAuthUrlError(msg);
      toast.error('Credential validation failed', { description: msg });
    } finally {
      setSavingCreds(false);
    }
  };

  const handleAuthorize = async () => {
    if (!authUrl) return;

    // Snapshot the *current* connection state so the polling loop can
    // tell "second channel just landed" apart from "first channel was
    // already there before we started". Without this delta the wizard
    // would fire onConnected immediately whenever any previous channel
    // existed, looking like it succeeded without the user signing in.
    const snapshot = await spec.snapshotConnections();

    // Open the OAuth URL in the system's default browser via Tauri's
    // opener plugin. Inside the Tauri webview, ``window.open`` is
    // unreliable (it sometimes routes back into the same view, killing
    // the SPA), and the previous "window.location.href =" pattern took
    // the whole webview to Google and stranded the user on the JSON
    // response page afterwards. The system browser handles the entire
    // OAuth dance while Drevalis stays alive in the background.
    try {
      await openExternal(authUrl);
    } catch (err) {
      toast.error('Could not open browser', {
        description: 'Open the authorize URL manually below to continue.',
      });
      // Fall through — user can click the link rendered in the step.
      return;
    }

    setStep('verify');
    setPolling(true);
    setVerifyError(null);

    // Poll every 2s for up to 5 minutes. Stop when:
    //   - a new connection appears (vs the pre-auth snapshot), or
    //   - the timeout fires (user abandoned the flow).
    const startedAt = Date.now();
    const interval = setInterval(async () => {
      const elapsed = Date.now() - startedAt;
      if (elapsed > 5 * 60_000) {
        clearInterval(interval);
        setPolling(false);
        setVerifyError(
          'Timed out waiting for the OAuth callback. Finish the consent in your browser, or click Try again.',
        );
        return;
      }
      try {
        const fresh = await spec.hasNewConnection(snapshot);
        if (fresh) {
          clearInterval(interval);
          setPolling(false);
          toast.success(`${spec.label} connected`);
          onConnected?.();
        }
      } catch {
        /* keep polling — transient errors are fine */
      }
    }, 2000);
  };

  const Icon = spec.icon;

  // ── Step renderers ──────────────────────────────────────────────────

  const introStep = (
    <div className="space-y-4 text-sm">
      <div className="flex items-start gap-3">
        <Icon size={20} className="text-accent shrink-0 mt-0.5" />
        <div>
          <p className="text-txt-primary">
            We&rsquo;ll walk you through connecting your {spec.label} account in
            four short steps. Drevalis runs locally, so the OAuth credentials
            you create here belong to <strong>your</strong> {spec.label}{' '}
            developer account &mdash; nothing is shared with us.
          </p>
        </div>
      </div>

      <div className="rounded-md border border-border bg-bg-elevated p-3 space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wider text-txt-tertiary">
          What you&rsquo;ll need
        </p>
        <ol className="list-decimal pl-5 space-y-1 text-txt-secondary text-[13px]">
          {spec.setupSteps.map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ol>
        <a
          href={spec.portalUrl}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-accent hover:underline text-[12px] mt-2"
        >
          Open {spec.portalLabel} <ExternalLink size={11} />
        </a>
      </div>

      <div className="rounded-md border border-border bg-bg-elevated p-3 space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wider text-txt-tertiary">
          Redirect URI &mdash; paste this into the provider portal
        </p>
        <div className="flex items-center gap-2">
          <code className="flex-1 text-[12px] font-mono text-txt-primary bg-bg-base rounded px-2 py-1.5 overflow-x-auto">
            {spec.defaultRedirectUri}
          </code>
          <Button variant="ghost" size="sm" onClick={copyRedirect} aria-label="Copy redirect URI">
            <Copy size={13} />
          </Button>
        </div>
        <p className="text-[11px] text-txt-tertiary">
          Must be added <em>verbatim</em> to the OAuth client&rsquo;s allowed
          redirect URIs in {spec.label}&rsquo;s portal &mdash; otherwise the
          callback step will fail.
        </p>
      </div>

      <div className="rounded-md border border-border bg-bg-elevated p-3 space-y-1">
        <p className="text-xs font-semibold uppercase tracking-wider text-txt-tertiary">
          Scopes you&rsquo;ll be granting
        </p>
        <ul className="list-disc pl-5 text-txt-secondary text-[13px] space-y-0.5">
          {spec.scopes.map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ul>
      </div>
    </div>
  );

  const credentialsStep = (
    <div className="space-y-4 text-sm">
      <p className="text-txt-secondary">
        Paste the values from your {spec.label} developer app. Both are stored
        encrypted at rest with Fernet (your local <code>ENCRYPTION_KEY</code>),
        and the secret is never echoed back to the UI.
      </p>
      {spec.credentialKeys.map((k) => {
        const isSensitive = k.sensitive;
        const isShown = revealed[k.keyName] === true;
        return (
          <div key={k.keyName} className="space-y-1">
            <label className="text-xs font-medium text-txt-secondary block">
              {k.label}
            </label>
            <div className="relative">
              <Input
                type={isSensitive && !isShown ? 'password' : 'text'}
                value={creds[k.keyName] ?? ''}
                onChange={(e) =>
                  setCreds((prev) => ({ ...prev, [k.keyName]: e.target.value }))
                }
                placeholder={k.placeholder}
                className="font-mono text-xs pr-10"
                autoComplete="off"
                spellCheck={false}
              />
              {isSensitive && (
                <button
                  type="button"
                  onClick={() =>
                    setRevealed((p) => ({ ...p, [k.keyName]: !p[k.keyName] }))
                  }
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded text-txt-tertiary hover:text-txt-primary"
                  aria-label={isShown ? 'Hide value' : 'Reveal value'}
                  tabIndex={-1}
                >
                  {isShown ? <EyeOff size={13} /> : <Eye size={13} />}
                </button>
              )}
            </div>
            <p className="text-[11px] text-txt-tertiary">{k.helper}</p>
          </div>
        );
      })}

      {authUrlError && (
        <div className="rounded-md border border-error/30 bg-error/5 p-3 text-[12px] text-error flex items-start gap-2">
          <AlertTriangle size={13} className="shrink-0 mt-0.5" />
          <span>{authUrlError}</span>
        </div>
      )}
    </div>
  );

  const authorizeStep = (
    <div className="space-y-4 text-sm">
      <div className="flex items-start gap-3">
        <CheckCircle2 size={18} className="text-success shrink-0 mt-0.5" />
        <div>
          <p className="text-txt-primary font-medium">Ready to connect.</p>
          <p className="text-txt-secondary mt-0.5">
            We&rsquo;ll open {spec.label} in your default web browser so you can
            sign in and grant the permissions listed earlier. Leave Drevalis
            open in the background &mdash; the wizard polls every two seconds
            and closes itself the moment a new connection appears.
          </p>
        </div>
      </div>

      <div className="rounded-md border border-accent/20 bg-accent/[0.04] p-3 text-[12px] text-txt-secondary">
        Adding more than one {spec.label} account / channel? Sign out of any
        other {spec.label} session in your browser first, or use a private
        window for this one &mdash; otherwise Google may auto-select the
        previous account and reconnect that one instead of the new one.
      </div>

      {authUrl && (
        <div className="rounded-md border border-border bg-bg-elevated p-3 space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wider text-txt-tertiary">
            If your browser doesn&rsquo;t open
          </p>
          <p className="text-[11px] text-txt-tertiary">
            Copy this URL into a browser yourself:
          </p>
          <code className="block text-[11px] font-mono text-txt-tertiary bg-bg-base rounded px-2 py-1.5 overflow-x-auto break-all">
            {authUrl}
          </code>
        </div>
      )}

      {authUrlError && (
        <div className="rounded-md border border-error/30 bg-error/5 p-3 text-[12px] text-error flex items-start gap-2">
          <AlertTriangle size={13} className="shrink-0 mt-0.5" />
          <span>{authUrlError}</span>
        </div>
      )}
    </div>
  );

  const verifyStep = (
    <div className="space-y-4 text-sm">
      {polling ? (
        <div className="flex items-start gap-3">
          <Loader2 size={18} className="text-accent animate-spin shrink-0 mt-0.5" />
          <div>
            <p className="text-txt-primary font-medium">Waiting for {spec.label}&hellip;</p>
            <p className="text-txt-secondary mt-0.5">
              Finish the consent screen in your browser. We&rsquo;re polling
              every two seconds and will close this dialog the moment the new
              connection lands.
            </p>
          </div>
        </div>
      ) : verifyError ? (
        <div className="space-y-3">
          <div className="rounded-md border border-error/30 bg-error/5 p-3 text-[12px] text-error flex items-start gap-2">
            <AlertTriangle size={13} className="shrink-0 mt-0.5" />
            <span>{verifyError}</span>
          </div>
          <Button variant="secondary" size="sm" onClick={handleAuthorize}>
            <Sparkles size={13} /> Try again
          </Button>
        </div>
      ) : (
        <div className="flex items-start gap-3">
          <CheckCircle2 size={18} className="text-success shrink-0 mt-0.5" />
          <div>
            <p className="text-txt-primary font-medium">All set.</p>
            <p className="text-txt-secondary mt-0.5">
              {spec.label} is connected. You can close this dialog &mdash; the
              connection will appear in the {spec.label} page.
            </p>
          </div>
        </div>
      )}
    </div>
  );

  // ── Step plumbing ───────────────────────────────────────────────────

  const stepIndex: Record<Step, number> = {
    intro: 1,
    credentials: 2,
    authorize: 3,
    verify: 4,
  };
  const totalSteps = 4;

  const stepBody =
    step === 'intro'
      ? introStep
      : step === 'credentials'
        ? credentialsStep
        : step === 'authorize'
          ? authorizeStep
          : verifyStep;

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={`Connect ${spec.label}`}
      maxWidth="lg"
    >
      <div className="space-y-3">
        {/* Step indicator */}
        <div className="flex items-center gap-2 text-[11px] text-txt-tertiary">
          <Badge variant="accent">
            Step {stepIndex[step]} of {totalSteps}
          </Badge>
          <span className="capitalize">{step}</span>
        </div>

        {stepBody}
      </div>

      <DialogFooter>
        {step !== 'intro' && step !== 'verify' && (
          <Button
            variant="ghost"
            onClick={() =>
              setStep(step === 'authorize' ? 'credentials' : 'intro')
            }
          >
            <ChevronLeft size={14} /> Back
          </Button>
        )}
        <Button variant="ghost" onClick={onClose}>
          {step === 'verify' && !polling && !verifyError ? 'Done' : 'Cancel'}
        </Button>

        {step === 'intro' && (
          <Button variant="primary" onClick={() => setStep('credentials')}>
            I have my credentials <ChevronRight size={14} />
          </Button>
        )}
        {step === 'credentials' && (
          <Button
            variant="primary"
            disabled={!allCredsFilled || savingCreds}
            loading={savingCreds}
            onClick={() => void handleSaveCreds()}
          >
            Save & validate <ChevronRight size={14} />
          </Button>
        )}
        {step === 'authorize' && (
          <Button variant="primary" onClick={handleAuthorize}>
            Open {spec.label} consent <ExternalLink size={13} />
          </Button>
        )}
      </DialogFooter>
    </Dialog>
  );
}

export default SocialConnectWizard;
