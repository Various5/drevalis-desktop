import { useState, useEffect, useCallback, useRef } from 'react';
import {
  CheckCircle2,
  XCircle,
  AlertCircle,
  RefreshCw,
  Key,
  Plus,
  Trash2,
  Eye,
  EyeOff,
  Zap,
} from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Select } from '@/components/ui/Select';
import { Badge } from '@/components/ui/Badge';
import { Dialog, DialogFooter } from '@/components/ui/Dialog';
import { Spinner } from '@/components/ui/Spinner';
import { apiKeys as apiKeysApi } from '@/lib/api';

// ---------------------------------------------------------------------------
// Constants / helpers
// ---------------------------------------------------------------------------

export const KEY_NAME_OPTIONS = [
  { value: 'runpod', label: 'RunPod API Key' },
  { value: 'vastai_api_key', label: 'Vast.ai API Key' },
  { value: 'lambda_api_key', label: 'Lambda Labs API Key' },
  { value: 'elevenlabs', label: 'ElevenLabs API Key' },
  { value: 'anthropic', label: 'Anthropic API Key' },
  { value: 'openai', label: 'OpenAI API Key' },
  { value: 'tiktok_client_key', label: 'TikTok Client Key' },
  { value: 'tiktok_client_secret', label: 'TikTok Client Secret' },
  { value: 'tiktok_redirect_uri', label: 'TikTok Redirect URI' },
  { value: 'instagram', label: 'Instagram API Key' },
  { value: 'facebook_page_access_token', label: 'Facebook Page Access Token' },
  { value: 'facebook_page_id', label: 'Facebook Page ID' },
  { value: 'youtube_client_id', label: 'YouTube Client ID' },
  { value: 'youtube_client_secret', label: 'YouTube Client Secret' },
  { value: 'hf_token', label: 'HuggingFace Token' },
];

export function sourceLabel(source: string): string {
  if (source === 'db') return 'Database';
  if (source === 'env') return 'Environment';
  return source;
}

export function sourceBadgeVariant(source: string): string {
  if (source === 'db') return 'accent';
  if (source === 'env') return 'info';
  return 'neutral';
}

// ---------------------------------------------------------------------------
// Local types
// ---------------------------------------------------------------------------

interface ApiKeyRecord {
  key_name: string;
  created_at: string;
  updated_at: string;
}

interface IntegrationInfo {
  configured: boolean;
  source: string;
}

const INTEGRATION_DEFS: Array<{
  id: string;
  label: string;
  description: string;
  iconBg: string;
  iconColor: string;
}> = [
  {
    id: 'runpod',
    label: 'RunPod',
    description: 'Cloud GPU pods — manage at /cloud-gpu',
    iconBg: 'bg-violet-500/10',
    iconColor: 'text-violet-400',
  },
  {
    id: 'vast_ai',
    label: 'Vast.ai',
    description: 'Spot-market GPU pods — manage at /cloud-gpu',
    iconBg: 'bg-sky-500/10',
    iconColor: 'text-sky-400',
  },
  {
    id: 'lambda_labs',
    label: 'Lambda Labs',
    description: 'On-demand A100/H100 — manage at /cloud-gpu',
    iconBg: 'bg-teal-500/10',
    iconColor: 'text-teal-400',
  },
  {
    id: 'elevenlabs',
    label: 'ElevenLabs',
    description: 'Premium text-to-speech voices',
    iconBg: 'bg-amber-500/10',
    iconColor: 'text-amber-400',
  },
  {
    id: 'anthropic',
    label: 'Anthropic',
    description: 'Claude LLM for script generation',
    iconBg: 'bg-orange-500/10',
    iconColor: 'text-orange-400',
  },
  {
    id: 'youtube',
    label: 'YouTube',
    description: 'Direct video upload via OAuth',
    iconBg: 'bg-red-500/10',
    iconColor: 'text-red-400',
  },
];

// ---------------------------------------------------------------------------
// ApiKeysSection
// ---------------------------------------------------------------------------

export function ApiKeysSection({ onNavigateToApiKeys: _onNavigateToApiKeys }: { onNavigateToApiKeys: () => void }) {
  const [keys, setKeys] = useState<ApiKeyRecord[]>([]);
  const [integrations, setIntegrations] = useState<Record<string, IntegrationInfo>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [deletingKey, setDeletingKey] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Form
  const [formKeyName, setFormKeyName] = useState('runpod');
  const [formApiKey, setFormApiKey] = useState('');
  const [showApiKey, setShowApiKey] = useState(false);

  const successTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const showSuccess = (msg: string) => {
    setSuccessMsg(msg);
    if (successTimer.current) clearTimeout(successTimer.current);
    successTimer.current = setTimeout(() => setSuccessMsg(null), 3500);
  };

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [keysRes, intRes] = await Promise.all([
        apiKeysApi.list(),
        apiKeysApi.integrations(),
      ]);
      setKeys(Array.isArray(keysRes) ? (keysRes as ApiKeyRecord[]) : ((keysRes as { items?: ApiKeyRecord[] }).items ?? []));
      setIntegrations(intRes as Record<string, IntegrationInfo>);
    } catch {
      // non-fatal
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  const handleSave = async () => {
    if (!formKeyName || !formApiKey.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await apiKeysApi.store(formKeyName, formApiKey.trim());
      setFormApiKey('');
      showSuccess(`${formKeyName} API key saved successfully.`);
      void fetchData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save API key.');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (keyName: string) => {
    setDeletingKey(keyName);
    try {
      await apiKeysApi.remove(keyName);
      showSuccess(`${keyName} API key removed.`);
      void fetchData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete API key.');
    } finally {
      setDeletingKey(null);
      setConfirmDelete(null);
    }
  };

  if (loading) return <Spinner />;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h3 className="text-lg font-semibold text-txt-primary">API Keys</h3>
        <p className="text-sm text-txt-secondary mt-0.5">
          Manage encrypted API keys for third-party services. Keys are stored encrypted at rest.
        </p>
      </div>

      {/* Success / Error banners */}
      {successMsg && (
        <div
          className="flex items-center gap-2 px-3 py-2.5 rounded-lg bg-success-muted text-success text-sm"
          role="status"
          aria-live="polite"
        >
          <CheckCircle2 size={14} className="shrink-0" />
          {successMsg}
        </div>
      )}
      {error && (
        <div
          className="flex items-center gap-2 px-3 py-2.5 rounded-lg bg-error-muted text-error text-sm"
          role="alert"
          aria-live="assertive"
        >
          <AlertCircle size={14} className="shrink-0" />
          {error}
          <button
            className="ml-auto text-error/60 hover:text-error transition-colors"
            onClick={() => setError(null)}
            aria-label="Dismiss error"
          >
            <XCircle size={14} />
          </button>
        </div>
      )}

      {/* Integration Status Grid */}
      <Card padding="md">
        <h4 className="text-sm font-semibold text-txt-primary mb-3 flex items-center gap-2">
          <Zap size={14} className="text-accent" />
          Integration Status
        </h4>
        <div className="grid grid-cols-2 gap-3">
          {INTEGRATION_DEFS.map((def) => {
            const info = integrations[def.id];
            const configured = info?.configured ?? false;
            const source = info?.source ?? 'Not configured';
            return (
              <div
                key={def.id}
                className="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-bg-hover border border-border"
              >
                <div className={['w-8 h-8 rounded-lg flex items-center justify-center shrink-0', def.iconBg].join(' ')}>
                  <Key size={14} className={def.iconColor} />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-txt-primary leading-tight">{def.label}</p>
                  <p className="text-[11px] text-txt-tertiary leading-tight mt-0.5 truncate">{def.description}</p>
                </div>
                <div className="shrink-0 flex flex-col items-end gap-1">
                  {configured ? (
                    <CheckCircle2 size={15} className="text-success" aria-label="Configured" />
                  ) : (
                    <XCircle size={15} className="text-txt-tertiary/50" aria-label="Not configured" />
                  )}
                  {configured && (
                    <Badge variant={sourceBadgeVariant(source)} className="text-[10px] leading-none">
                      {sourceLabel(source)}
                    </Badge>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </Card>

      {/* Stored Keys List */}
      <Card padding="md">
        <div className="flex items-center justify-between mb-3">
          <h4 className="text-sm font-semibold text-txt-primary flex items-center gap-2">
            <Key size={14} className="text-accent" />
            Stored Keys
          </h4>
          <Button variant="ghost" size="sm" onClick={() => void fetchData()}>
            <RefreshCw size={12} />
            Refresh
          </Button>
        </div>

        {keys.length === 0 ? (
          <div className="py-8 text-center">
            <Key size={24} className="mx-auto text-txt-tertiary/40 mb-2" />
            <p className="text-sm text-txt-tertiary">No API keys stored in database.</p>
            <p className="text-xs text-txt-tertiary/70 mt-0.5">
              Keys set via environment variables are shown in Integration Status above.
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {keys.map((k) => {
              const intInfo = integrations[k.key_name];
              return (
                <div
                  key={k.key_name}
                  className="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-bg-hover border border-border group"
                >
                  <div className="w-7 h-7 rounded-md bg-accent-muted flex items-center justify-center shrink-0">
                    <Key size={12} className="text-accent" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-mono font-medium text-txt-primary">{k.key_name}</span>
                      <Badge variant="success" className="text-[10px]">Configured</Badge>
                      {intInfo?.source && (
                        <Badge variant={sourceBadgeVariant(intInfo.source)} className="text-[10px]">
                          {sourceLabel(intInfo.source)}
                        </Badge>
                      )}
                    </div>
                    <p className="text-[11px] text-txt-tertiary mt-0.5">
                      Added {new Date(k.created_at).toLocaleDateString()}
                      {k.updated_at !== k.created_at && (
                        <span> · Updated {new Date(k.updated_at).toLocaleDateString()}</span>
                      )}
                    </p>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    loading={deletingKey === k.key_name}
                    onClick={() => setConfirmDelete(k.key_name)}
                    className="opacity-0 group-hover:opacity-100 transition-opacity text-txt-tertiary hover:text-error shrink-0"
                    aria-label={`Delete ${k.key_name} API key`}
                  >
                    <Trash2 size={13} />
                  </Button>
                </div>
              );
            })}
          </div>
        )}
      </Card>

      {/* Add New Key */}
      <Card padding="md">
        <h4 className="text-sm font-semibold text-txt-primary mb-3 flex items-center gap-2">
          <Plus size={14} className="text-accent" />
          Add New Key
        </h4>
        <div className="space-y-3">
          <Select
            label="Service"
            value={formKeyName}
            onChange={(e) => setFormKeyName(e.target.value)}
            options={KEY_NAME_OPTIONS}
          />
          <div>
            <label className="block text-xs font-medium text-txt-secondary mb-1" htmlFor="new-api-key-input">
              API Key
            </label>
            <div className="relative">
              <input
                id="new-api-key-input"
                type={showApiKey ? 'text' : 'password'}
                value={formApiKey}
                onChange={(e) => setFormApiKey(e.target.value)}
                placeholder="Paste your API key here..."
                className="w-full h-8 pr-10 pl-2.5 text-sm text-txt-primary bg-bg-elevated border border-border rounded placeholder:text-txt-tertiary focus:border-accent focus:shadow-accent-glow transition-all duration-fast font-mono"
                aria-describedby="api-key-hint"
              />
              <button
                type="button"
                onClick={() => setShowApiKey((v) => !v)}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-txt-tertiary hover:text-txt-secondary transition-colors"
                aria-label={showApiKey ? 'Hide API key' : 'Show API key'}
              >
                {showApiKey ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </div>
            <p id="api-key-hint" className="text-[11px] text-txt-tertiary mt-1">
              Your key is encrypted before being stored in the database.
            </p>
          </div>
          <div className="flex justify-end">
            <Button
              variant="primary"
              size="sm"
              loading={saving}
              disabled={!formKeyName || !formApiKey.trim()}
              onClick={() => void handleSave()}
            >
              <Key size={13} />
              Save Key
            </Button>
          </div>
        </div>
      </Card>

      {/* Delete confirmation dialog */}
      <Dialog
        open={confirmDelete !== null}
        onClose={() => setConfirmDelete(null)}
        title="Delete API Key"
      >
        <p className="text-sm text-txt-secondary">
          Are you sure you want to delete the <strong className="text-txt-primary">{confirmDelete}</strong> API key?
          This action cannot be undone. If the service relies on this key, it will stop working.
        </p>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setConfirmDelete(null)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            loading={deletingKey === confirmDelete}
            onClick={() => confirmDelete && void handleDelete(confirmDelete)}
          >
            <Trash2 size={13} />
            Delete Key
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}
