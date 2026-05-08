import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Cpu,
  Play,
  Square,
  Trash2,
  Plus,
  RefreshCw,
  AlertTriangle,
  ExternalLink,
  Check,
  X,
  Key,
} from 'lucide-react';
import { useToast } from '@/components/ui/Toast';
import { Dialog, DialogFooter } from '@/components/ui/Dialog';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { PageHeader } from '@/components/ui/PageHeader';
import { EmptyState } from '@/components/ui/EmptyState';
import { TierGatePlaceholder } from '@/components/TierGatePlaceholder';
import { ApiError } from '@/lib/api';

interface ProviderStatus {
  name: string;
  display_name: string;
  configured: boolean;
  api_key_name: string;
  docs_url: string;
}

interface Pod {
  id: string;
  name: string;
  status:
    | 'queued'
    | 'starting'
    | 'running'
    | 'stopping'
    | 'stopped'
    | 'terminated'
    | 'error';
  gpu_type_id: string;
  public_url: string | null;
  hourly_usd: number;
  started_at: string | null;
  provider: string;
  metadata?: Record<string, unknown>;
}

interface GpuType {
  id: string;
  label: string;
  vram_gb: number;
  hourly_usd: number;
  provider: string;
  region: string | null;
}

const STATUS_COLORS: Record<Pod['status'], string> = {
  queued: 'text-txt-muted bg-bg-elevated',
  starting: 'text-amber-300 bg-amber-500/10',
  running: 'text-accent bg-accent/10',
  stopping: 'text-amber-300 bg-amber-500/10',
  stopped: 'text-txt-secondary bg-bg-elevated',
  terminated: 'text-txt-muted bg-bg-elevated',
  error: 'text-rose-300 bg-rose-500/10',
};

export default function CloudGPUPage() {
  const { toast } = useToast();
  const [providers, setProviders] = useState<ProviderStatus[]>([]);
  const [pods, setPods] = useState<Pod[]>([]);
  const [loading, setLoading] = useState(true);
  const [launchOpen, setLaunchOpen] = useState(false);
  const [launchProvider, setLaunchProvider] = useState<string>('');
  const [gpuTypes, setGpuTypes] = useState<GpuType[]>([]);
  const [gpuLoading, setGpuLoading] = useState(false);
  const [newGpu, setNewGpu] = useState('');
  const [newName, setNewName] = useState('');
  const [newDisk, setNewDisk] = useState(40);
  const [launching, setLaunching] = useState(false);
  const [actionOn, setActionOn] = useState<string | null>(null);
  // Synthetic ApiError captured when the gated /cloud-gpu/* routes
  // 402. Renders the upgrade card in place of the page body.
  const [tierError, setTierError] = useState<ApiError | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [provResp, podsResp] = await Promise.all([
        fetch('/api/v1/cloud-gpu/providers'),
        fetch('/api/v1/cloud-gpu/pods'),
      ]);
      // Both endpoints share the same ``runpod`` feature gate; one 402
      // is enough to know the whole page should render the upgrade
      // card. Build a synthetic ApiError carrying the body so the
      // placeholder can pull tier / current_tier from detailRaw.
      const gatedResp = provResp.status === 402
        ? provResp
        : podsResp.status === 402
          ? podsResp
          : null;
      if (gatedResp) {
        const body = await gatedResp.json().catch(() => ({}));
        setTierError(new ApiError(402, gatedResp.statusText, undefined, body?.detail ?? body));
        return;
      }
      setTierError(null);
      if (provResp.ok) setProviders(await provResp.json());
      if (podsResp.ok) setPods(await podsResp.json());
    } catch (err) {
      toast.error('Could not load cloud GPU state', { description: String(err) });
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void refresh();
    const id = setInterval(() => void refresh(), 30_000);
    return () => clearInterval(id);
  }, [refresh]);

  const openLaunch = async (provider: string) => {
    setLaunchProvider(provider);
    setLaunchOpen(true);
    setGpuLoading(true);
    setNewGpu('');
    setNewName('');
    setGpuTypes([]);
    try {
      const r = await fetch(`/api/v1/cloud-gpu/${provider}/gpu-types`);
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d?.detail?.hint || d?.detail?.message || `HTTP ${r.status}`);
      }
      const list: GpuType[] = await r.json();
      setGpuTypes(list);
      if (list.length > 0) setNewGpu(list[0]!.id);
      setNewName(`drevalis-${provider}-${Date.now().toString().slice(-6)}`);
    } catch (err) {
      toast.error(`${provider}: failed to load GPU catalogue`, { description: String(err) });
    } finally {
      setGpuLoading(false);
    }
  };

  const launch = async () => {
    if (!launchProvider || !newGpu || !newName.trim()) return;
    setLaunching(true);
    try {
      const r = await fetch(`/api/v1/cloud-gpu/${launchProvider}/pods`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ gpu_type_id: newGpu, name: newName.trim(), disk_gb: newDisk }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d?.detail?.message || d?.detail || `HTTP ${r.status}`);
      }
      toast.success(`Launched on ${launchProvider}`, {
        description: 'Pod will appear in the list in ~1 minute.',
      });
      setLaunchOpen(false);
      await refresh();
    } catch (err) {
      toast.error('Launch failed', { description: String(err) });
    } finally {
      setLaunching(false);
    }
  };

  const podAction = async (pod: Pod, action: 'stop' | 'start' | 'delete') => {
    setActionOn(pod.id);
    try {
      const url =
        action === 'delete'
          ? `/api/v1/cloud-gpu/${pod.provider}/pods/${pod.id}`
          : `/api/v1/cloud-gpu/${pod.provider}/pods/${pod.id}/${action}`;
      const r = await fetch(url, { method: action === 'delete' ? 'DELETE' : 'POST' });
      if (!r.ok && r.status !== 204) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d?.detail?.message || d?.detail || `HTTP ${r.status}`);
      }
      toast.success(`Pod ${action === 'delete' ? 'deleted' : action + 'ped'}`);
      await refresh();
    } catch (err) {
      toast.error(`${action} failed`, { description: String(err) });
    } finally {
      setActionOn(null);
    }
  };

  if (tierError) {
    return (
      <div className="max-w-2xl mx-auto py-8">
        <TierGatePlaceholder error={tierError} featureLabel="Cloud GPU" />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        subtitle={
          <>
            Launch on-demand GPU pods across RunPod, Vast.ai, and Lambda
            Labs. Use them to offload ComfyUI scene generation or host a
            vLLM endpoint when your local GPU isn&rsquo;t enough. All pod
            management lives on this page — add or update the provider
            API keys in{' '}
            <Link
              to="/settings"
              className="text-accent hover:underline inline-flex items-center gap-1"
            >
              Settings → API Keys
              <Key size={11} />
            </Link>
            .
          </>
        }
        actions={
          <Button variant="ghost" size="sm" onClick={() => void refresh()}>
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Refresh
          </Button>
        }
      />

      {/* Provider status strip — equal-height cards, status pill on top
          row, action row pinned to the bottom. Internal key names like
          ``vastai_api_key`` are hidden when not connected (they leaked
          implementation detail into the UI); instead we surface the
          link to Settings → API Keys. */}
      <section className="grid grid-cols-1 md:grid-cols-3 gap-3 items-stretch">
        {providers.map((p) => (
          <div
            key={p.name}
            className={`rounded-lg border p-4 flex flex-col gap-3 h-full ${
              p.configured ? 'border-border bg-bg-elevated' : 'border-amber-500/30 bg-amber-500/5'
            }`}
          >
            <div className="flex items-start justify-between gap-2">
              <div className="flex items-center gap-2 min-w-0">
                <Cpu size={14} className={p.configured ? 'text-accent' : 'text-amber-400'} />
                <span className="font-semibold text-sm text-txt-primary truncate">{p.display_name}</span>
              </div>
              {p.configured ? (
                <span className="shrink-0 text-[10px] text-accent border border-accent/30 rounded px-1.5 py-0.5 inline-flex items-center gap-1 whitespace-nowrap">
                  <Check size={10} /> Connected
                </span>
              ) : (
                <span className="shrink-0 text-[10px] text-amber-300 border border-amber-400/30 rounded px-1.5 py-0.5 inline-flex items-center gap-1 whitespace-nowrap">
                  <X size={10} /> Not connected
                </span>
              )}
            </div>

            {p.configured ? (
              // Concrete pricing cue — pulled from the GPU catalogue
              // when the launch modal opens; until then we just show
              // the tagline so each card has parallel content.
              <p className="text-[11px] text-txt-muted">
                On-demand GPU pods · pay-per-hour
              </p>
            ) : (
              <Link
                to="/settings"
                className="text-[11px] text-accent hover:underline inline-flex items-center gap-1 self-start"
              >
                <Key size={11} /> Add API key in Settings
              </Link>
            )}

            {!p.configured && (
              <a
                href={p.docs_url}
                target="_blank"
                rel="noreferrer"
                className="text-[11px] text-txt-secondary hover:text-accent hover:underline inline-flex items-center gap-1 self-start"
              >
                Get an API key from {p.display_name} <ExternalLink size={10} />
              </a>
            )}

            <div className="mt-auto pt-2 flex justify-end">
              <Button
                variant={p.configured ? 'primary' : 'ghost'}
                size="sm"
                disabled={!p.configured}
                onClick={() => void openLaunch(p.name)}
              >
                <Plus size={12} /> Launch
              </Button>
            </div>
          </div>
        ))}
      </section>

      {/* Unified pod list */}
      <section className="rounded-lg border border-border bg-bg-elevated">
        <div className="px-4 py-3 border-b border-border flex items-center justify-between">
          <h2 className="text-sm font-semibold text-txt-primary">Active pods ({pods.length})</h2>
          <p className="text-[11px] text-txt-muted">Polling every 30 s</p>
        </div>
        {pods.length === 0 ? (
          <EmptyState
            icon={Cpu}
            title="No active pods"
            description="Click Launch on a connected provider above to spin up a GPU pod."
          />
        ) : (
          <div className="divide-y divide-border">
            {pods.map((pod) => {
              const isBusy = actionOn === pod.id;
              return (
                <div
                  key={`${pod.provider}-${pod.id}`}
                  className="px-4 py-3 grid grid-cols-[1fr_auto] gap-3 items-center"
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-medium text-sm text-txt-primary truncate">
                        {pod.name}
                      </span>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded font-mono ${STATUS_COLORS[pod.status]}`}>
                        {pod.status}
                      </span>
                      <span className="text-[10px] text-txt-muted uppercase tracking-wider">
                        {pod.provider}
                      </span>
                      <span className="text-[10px] text-txt-secondary">
                        {pod.gpu_type_id}
                      </span>
                      {pod.hourly_usd > 0 && (
                        <span className="text-[10px] text-txt-muted">
                          ${pod.hourly_usd.toFixed(3)}/hr
                        </span>
                      )}
                    </div>
                    {pod.public_url && (
                      <a
                        href={pod.public_url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-[11px] text-accent hover:underline font-mono inline-flex items-center gap-1 mt-1"
                      >
                        {pod.public_url} <ExternalLink size={10} />
                      </a>
                    )}
                  </div>
                  <div className="flex gap-1">
                    {pod.status === 'running' && (
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={isBusy}
                        onClick={() => void podAction(pod, 'stop')}
                        title="Stop (keeps pod, billing pauses on some providers)"
                        aria-label={`Stop pod ${pod.name}`}
                      >
                        <Square size={12} />
                      </Button>
                    )}
                    {pod.status === 'stopped' && (
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={isBusy}
                        onClick={() => void podAction(pod, 'start')}
                        title="Start pod"
                        aria-label={`Start pod ${pod.name}`}
                      >
                        <Play size={12} />
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={isBusy}
                      onClick={() => {
                        if (confirm(`Delete ${pod.name}? This terminates billing and wipes local state on the pod.`)) {
                          void podAction(pod, 'delete');
                        }
                      }}
                      className="text-error hover:bg-error/10"
                      title="Delete pod"
                      aria-label={`Delete pod ${pod.name}`}
                    >
                      <Trash2 size={12} />
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      <p className="text-xs text-txt-muted">
        <AlertTriangle size={12} className="inline mr-1 text-amber-400" />
        Costs are billed by the provider directly — Drevalis only orchestrates. Delete pods
        you aren't using.
      </p>

      {/* Launch dialog */}
      <Dialog
        open={launchOpen}
        onClose={() => setLaunchOpen(false)}
        title={`Launch on ${providers.find((p) => p.name === launchProvider)?.display_name ?? launchProvider}`}
        description="Pick a GPU tier and give the pod a name. Launch usually takes 30 s – 2 min."
        maxWidth="lg"
      >
        <div className="space-y-3 text-sm">
          <div>
            <label className="block text-xs text-txt-secondary mb-1">GPU type</label>
            {gpuLoading ? (
              <div className="flex items-center gap-2 text-xs text-txt-muted">
                <RefreshCw size={12} className="animate-spin" /> Loading GPU catalogue…
              </div>
            ) : gpuTypes.length === 0 ? (
              <p className="text-xs text-txt-muted">No GPU types available right now.</p>
            ) : (
              <select
                value={newGpu}
                onChange={(e) => setNewGpu(e.target.value)}
                className="w-full px-3 py-2 bg-bg-base border border-white/[0.08] rounded-md text-sm text-txt-primary focus:outline-none focus:border-accent/40"
              >
                {gpuTypes.map((g) => (
                  <option key={g.id} value={g.id}>
                    {g.label} — {g.vram_gb ? `${g.vram_gb} GB VRAM — ` : ''}$
                    {g.hourly_usd.toFixed(3)}/hr
                    {g.region ? ` · ${g.region}` : ''}
                  </option>
                ))}
              </select>
            )}
          </div>
          <div>
            <label className="block text-xs text-txt-secondary mb-1">Pod name</label>
            <Input value={newName} onChange={(e) => setNewName(e.target.value)} />
          </div>
          <div>
            <label className="block text-xs text-txt-secondary mb-1">
              Disk (GB) — {newDisk} GB
            </label>
            <input
              type="range"
              min={20}
              max={500}
              step={10}
              value={newDisk}
              onChange={(e) => setNewDisk(Number(e.target.value))}
              className="w-full accent-accent"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setLaunchOpen(false)}>
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={launching}
            disabled={launching || gpuLoading || !newGpu || !newName.trim()}
            onClick={() => void launch()}
          >
            Launch
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}
