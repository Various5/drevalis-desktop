import { useEffect, useState } from 'react';
import {
  Network,
  AlertTriangle,
  Copy,
  Check,
  Eye,
  EyeOff,
  RefreshCw,
} from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { ConfirmDangerousDialog } from '@/components/ui/ConfirmDangerousDialog';
import { isTauri, restartBackend } from '@/lib/tauri';

// ---------------------------------------------------------------------------
// NetworkSection — Settings → System → "LAN API Access".
//
// Lets the operator expose the local backend API to other machines on the
// network (binds 0.0.0.0 instead of 127.0.0.1). Because a desktop install
// has no login, this would otherwise mean an unauthenticated API on the LAN
// — so enabling it also turns on a bearer token that remote callers must
// send. The local app (loopback) is exempt and keeps working untouched.
//
// The bind host is read at backend startup, so changes need an app restart;
// the backend reports ``restart_required`` and we surface a banner.
// ---------------------------------------------------------------------------

interface NetworkState {
  lan_api_enabled: boolean;
  api_token: string | null;
  bind_host: string;
  runtime_bind_host: string | null;
  restart_required: boolean;
  port: number;
  lan_urls: string[];
}

export function NetworkSection() {
  const [state, setState] = useState<NetworkState | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [revealToken, setRevealToken] = useState(false);
  const [copied, setCopied] = useState<'token' | 'url' | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [rotating, setRotating] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const [restartError, setRestartError] = useState<string | null>(null);

  async function doRestart() {
    setRestartError(null);
    setRestarting(true);
    try {
      await restartBackend();
      // The backend just respawned with the new bind host; refetch so the
      // banner clears and ``runtime_bind_host`` matches ``bind_host``.
      await reload();
    } catch (err) {
      setRestartError(err instanceof Error ? err.message : String(err));
    } finally {
      setRestarting(false);
    }
  }

  async function reload() {
    setLoading(true);
    try {
      const res = await fetch('/api/v1/settings/network', { credentials: 'include' });
      if (res.ok) setState(await res.json());
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void reload();
  }, []);

  async function toggle(next: boolean) {
    setSaving(true);
    try {
      const res = await fetch('/api/v1/settings/network', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ lan_api_enabled: next }),
      });
      if (res.ok) setState(await res.json());
    } finally {
      setSaving(false);
    }
  }

  // Enabling exposes the API to the LAN — gate it behind the typed confirm.
  // Disabling is safe, so it applies immediately.
  function onToggleChange(next: boolean) {
    if (next) setConfirmOpen(true);
    else void toggle(false);
  }

  async function confirmEnable() {
    setConfirmOpen(false);
    await toggle(true);
  }

  async function rotateToken() {
    setRotating(true);
    try {
      const res = await fetch('/api/v1/settings/network/rotate-token', {
        method: 'POST',
        credentials: 'include',
      });
      if (res.ok) {
        setState(await res.json());
        setRevealToken(true);
      }
    } finally {
      setRotating(false);
    }
  }

  async function copy(text: string, kind: 'token' | 'url') {
    await navigator.clipboard.writeText(text);
    setCopied(kind);
    setTimeout(() => setCopied(null), 1500);
  }

  if (loading) return <Card className="p-6">Loading network settings…</Card>;
  if (!state) return <Card className="p-6">Couldn't load network settings.</Card>;

  const enabled = state.lan_api_enabled;

  return (
    <Card className="p-6 space-y-6">
      <header className="flex items-start gap-3">
        <Network className="w-6 h-6 text-accent flex-shrink-0 mt-0.5" />
        <div className="flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <h2 className="text-lg font-semibold">LAN API Access</h2>
            {enabled ? (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-xs font-medium text-amber-300">
                <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
                Exposed on LAN
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-success/40 bg-success/10 px-2 py-0.5 text-xs font-medium text-success">
                <span className="w-1.5 h-1.5 rounded-full bg-success" />
                Local only
              </span>
            )}
          </div>
          <p className="text-sm text-muted-foreground mt-1">
            By default the backend only accepts connections from this machine
            ({state.runtime_bind_host ?? '127.0.0.1'}). Turn this on to reach
            the API from other computers on your network — useful for managing
            a testing or staging install remotely.
          </p>
        </div>
      </header>

      {/* Toggle */}
      <div className="rounded-lg border border-border bg-background/60 p-4">
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="text-sm font-medium">Allow access from the network</p>
            <p className="text-xs text-muted-foreground mt-0.5">
              Binds the API to <code className="px-1 rounded bg-muted">0.0.0.0</code>{' '}
              instead of <code className="px-1 rounded bg-muted">127.0.0.1</code>.
            </p>
          </div>
          <label className="inline-flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              className="w-4 h-4 rounded accent-accent"
              checked={enabled}
              disabled={saving}
              onChange={(e) => onToggleChange(e.target.checked)}
            />
            <span className="text-sm">{enabled ? 'On' : 'Off'}</span>
          </label>
        </div>
      </div>

      {/* Security warning — always visible so the trade-off is explicit */}
      <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-4 flex items-start gap-3">
        <AlertTriangle className="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5" />
        <div className="text-sm text-amber-200/90 space-y-1">
          <p className="font-medium text-amber-200">Exposes the full API to your network.</p>
          <p>
            Anyone who can reach this machine on port {state.port} and has the
            token below can manage content, YouTube connections, and uploads.
            Only enable this on a network you trust, and keep the token secret.
            Remote requests must send{' '}
            <code className="px-1 rounded bg-black/30">Authorization: Bearer &lt;token&gt;</code>.
            The app on this machine never needs it.
          </p>
        </div>
      </div>

      {/* Restart banner — coloured strip at the top of the section.
          In the desktop shell, exposes a "Restart backend" button that calls
          the Rust ``restart_backend`` command (graceful kill + respawn,
          resolves once the API port is back). In a browser run the button is
          omitted; the inline copy still tells the user how to recover. */}
      {state.restart_required && (
        <div className="rounded-lg border border-accent/40 bg-accent-muted/40 p-4 flex items-start gap-3">
          <RefreshCw className={`w-5 h-5 text-accent flex-shrink-0 mt-0.5 ${restarting ? 'animate-spin' : ''}`} />
          <div className="flex-1 space-y-2">
            <p className="text-sm text-txt-secondary">
              <span className="font-medium text-txt-primary">Restart required.</span>{' '}
              The change is saved, but the API is still bound to{' '}
              <code className="px-1 rounded bg-muted">{state.runtime_bind_host}</code>.
              {isTauri()
                ? ' Restart the backend to start listening on '
                : ' Fully quit and reopen the app to start listening on '}
              <code className="px-1 rounded bg-muted">{state.bind_host}</code>.
            </p>
            {isTauri() && (
              <div className="flex items-center gap-3">
                <Button
                  size="sm"
                  onClick={() => void doRestart()}
                  loading={restarting}
                  disabled={restarting}
                >
                  Restart backend
                </Button>
                {restartError && (
                  <span className="text-xs text-error" role="alert">
                    {restartError}
                  </span>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Reachable URLs + token (only meaningful when enabled) */}
      {enabled && (
        <div className="rounded-lg border border-border bg-background/60 p-4 space-y-4">
          <div>
            <p className="text-sm font-medium mb-1.5">Reachable at</p>
            {state.lan_urls.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                No network address detected.
              </p>
            ) : (
              <ul className="space-y-1">
                {state.lan_urls.map((url) => (
                  <li key={url} className="flex items-center gap-2">
                    <code className="text-xs px-1.5 py-0.5 rounded bg-muted text-foreground">
                      {url}
                    </code>
                    <button
                      type="button"
                      onClick={() => void copy(url, 'url')}
                      className="text-muted-foreground hover:text-foreground"
                      title="Copy URL"
                    >
                      {copied === 'url' ? <Check size={13} /> : <Copy size={13} />}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div>
            <p className="text-sm font-medium mb-1.5">Access token</p>
            <div className="flex items-center gap-2">
              <code className="flex-1 text-xs px-2 py-1.5 rounded bg-muted text-foreground font-mono break-all">
                {state.api_token
                  ? revealToken
                    ? state.api_token
                    : '•'.repeat(Math.min(48, state.api_token.length))
                  : '(none)'}
              </code>
              <button
                type="button"
                onClick={() => setRevealToken((v) => !v)}
                className="text-muted-foreground hover:text-foreground p-1"
                title={revealToken ? 'Hide' : 'Reveal'}
              >
                {revealToken ? <EyeOff size={15} /> : <Eye size={15} />}
              </button>
              <button
                type="button"
                onClick={() => state.api_token && void copy(state.api_token, 'token')}
                disabled={!state.api_token}
                className="text-muted-foreground hover:text-foreground p-1 disabled:opacity-40"
                title="Copy token"
              >
                {copied === 'token' ? <Check size={15} /> : <Copy size={15} />}
              </button>
              <button
                type="button"
                onClick={() => void rotateToken()}
                disabled={rotating}
                className="text-muted-foreground hover:text-foreground p-1 disabled:opacity-40"
                title="Rotate token"
              >
                <RefreshCw size={15} className={rotating ? 'animate-spin' : ''} />
              </button>
            </div>
            <p className="mt-1.5 text-[11px] text-txt-tertiary">
              Rotating invalidates the current token. Restart the backend for the new
              token to take effect on LAN clients.
            </p>
          </div>
        </div>
      )}

      <div className="flex justify-end">
        <Button variant="ghost" size="sm" onClick={() => void reload()}>
          Refresh
        </Button>
      </div>

      <ConfirmDangerousDialog
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        onConfirm={() => void confirmEnable()}
        title="Expose the API on your network?"
        warning={
          <>
            This binds the backend to your whole network. Anyone who can reach this
            machine on port {state.port} and has the access token can manage your
            content, YouTube connections, and uploads. Only enable on a network you trust.
          </>
        }
        consequences={[
          'The API listens on all interfaces (0.0.0.0) after the next restart',
          'Remote callers authenticate with the bearer token shown here',
          'Keep the token secret; rotate it immediately if it leaks',
        ]}
        confirmWord="EXPOSE"
        confirmLabel="Enable LAN access"
        loading={saving}
      />
    </Card>
  );
}
