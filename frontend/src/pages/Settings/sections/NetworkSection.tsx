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
        <div>
          <h2 className="text-lg font-semibold">LAN API Access</h2>
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
              onChange={(e) => void toggle(e.target.checked)}
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

      {/* Restart banner */}
      {state.restart_required && (
        <div className="rounded-lg border border-accent/40 bg-accent-muted/40 p-4 flex items-start gap-3">
          <RefreshCw className="w-5 h-5 text-accent flex-shrink-0 mt-0.5" />
          <p className="text-sm text-txt-secondary">
            <span className="font-medium text-txt-primary">Restart required.</span>{' '}
            The change is saved, but the API is still bound to{' '}
            <code className="px-1 rounded bg-muted">{state.runtime_bind_host}</code>.
            Fully quit and reopen the app to start listening on{' '}
            <code className="px-1 rounded bg-muted">{state.bind_host}</code>.
          </p>
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
            </div>
          </div>
        </div>
      )}

      <div className="flex justify-end">
        <Button variant="ghost" size="sm" onClick={() => void reload()}>
          Refresh
        </Button>
      </div>
    </Card>
  );
}
