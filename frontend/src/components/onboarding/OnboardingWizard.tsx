import { useCallback, useEffect, useState } from 'react';
import {
  Check,
  ChevronRight,
  Cpu,
  Mic,
  Sparkles,
  Youtube,
  AlertCircle,
} from 'lucide-react';
import { Dialog } from '@/components/ui/Dialog';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { useToast } from '@/components/ui/Toast';
import {
  comfyuiServers,
  llmConfigs,
  onboarding as onboardingApi,
  voiceProfiles,
  formatError,
  type OnboardingStatus,
} from '@/lib/api';

/**
 * First-run onboarding wizard.
 *
 * Four sequential steps, each self-contained and individually skippable.
 * Skipping a *required* step (ComfyUI / LLM / Voice) leaves the dashboard
 * partially functional, but the app will prompt again on next load unless
 * the user clicks "Don't show again" at the end.
 *
 * Visibility is driven by /api/v1/onboarding/status — this component is
 * inert until `should_show` is true.
 */

type StepKey = 'comfyui' | 'llm' | 'voice' | 'youtube';

const STEPS: { key: StepKey; label: string; icon: typeof Cpu; required: boolean }[] = [
  { key: 'comfyui', label: 'ComfyUI', icon: Cpu, required: true },
  { key: 'llm', label: 'LLM endpoint', icon: Sparkles, required: true },
  { key: 'voice', label: 'Default voice', icon: Mic, required: true },
  { key: 'youtube', label: 'YouTube', icon: Youtube, required: false },
];

interface Props {
  status: OnboardingStatus;
  onRefresh: () => Promise<void> | void;
  onDismiss: () => Promise<void> | void;
}

export function OnboardingWizard({ status, onRefresh, onDismiss }: Props) {
  const { toast } = useToast();
  const [stepIdx, setStepIdx] = useState(0);
  const [open, setOpen] = useState(status.should_show);

  // Keep the modal in sync with external status changes (e.g. user
  // finishes a step through Settings directly; next poll flips should_show
  // to false).
  useEffect(() => {
    setOpen(status.should_show);
  }, [status.should_show]);

  const step = STEPS[stepIdx] ?? STEPS[0]!;
  const advance = () => setStepIdx((n) => Math.min(n + 1, STEPS.length - 1));
  const goTo = (k: StepKey) => setStepIdx(STEPS.findIndex((s) => s.key === k));

  const finish = useCallback(async () => {
    try {
      await onboardingApi.dismiss();
      await onDismiss();
      setOpen(false);
      toast.success('Onboarding dismissed', {
        description: 'Re-open any time from Settings → Help.',
      });
    } catch (err) {
      toast.error('Could not save dismissal', { description: formatError(err) });
    }
  }, [onDismiss, toast]);

  if (!open) return null;

  return (
    <Dialog
      open={open}
      onClose={() => void 0}
      title="Welcome to Drevalis Creator Studio"
      description="Three quick configs and you're ready to generate. Each step is independent — skip anything you'll fill in later."
      maxWidth="xl"
    >
      {/* Step nav pills */}
      <div className="flex items-center justify-between gap-2 mb-6">
        {STEPS.map((s, i) => {
          const done = isStepComplete(s.key, status);
          const active = i === stepIdx;
          const Icon = s.icon;
          return (
            <button
              key={s.key}
              onClick={() => setStepIdx(i)}
              className={`
                flex-1 flex items-center gap-2 px-3 py-2 rounded-md text-xs font-medium
                transition-colors
                ${
                  active
                    ? 'bg-accent/15 text-accent border border-accent/40'
                    : done
                      ? 'bg-bg-elevated text-txt-primary border border-transparent'
                      : 'bg-bg-elevated text-txt-muted border border-transparent hover:text-txt-secondary'
                }
              `}
            >
              <Icon size={14} />
              <span className="truncate">{s.label}</span>
              {done && <Check size={12} className="shrink-0 text-accent ml-auto" />}
              {!s.required && !done && (
                <span className="text-[10px] text-txt-muted ml-auto">optional</span>
              )}
            </button>
          );
        })}
      </div>

      {/* Step body */}
      <div className="min-h-[280px]">
        {step.key === 'comfyui' && (
          <ComfyUIStep
            done={status.comfyui_servers > 0}
            onSaved={async () => {
              await onRefresh();
              advance();
            }}
            onSkip={advance}
          />
        )}
        {step.key === 'llm' && (
          <LLMStep
            done={status.llm_configs > 0}
            onSaved={async () => {
              await onRefresh();
              advance();
            }}
            onSkip={advance}
          />
        )}
        {step.key === 'voice' && (
          <VoiceStep
            done={status.voice_profiles > 0}
            onSaved={async () => {
              await onRefresh();
              advance();
            }}
            onSkip={advance}
          />
        )}
        {step.key === 'youtube' && (
          <YouTubeStep
            done={status.youtube_channels > 0}
            onSkip={finish}
            onDone={finish}
          />
        )}
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between pt-5 mt-6 border-t border-white/[0.06]">
        <button
          onClick={() => void finish()}
          className="text-xs text-txt-muted hover:text-txt-secondary"
        >
          Skip onboarding — don't show again
        </button>
        <div className="flex items-center gap-2 text-xs text-txt-muted">
          <span>
            Step {stepIdx + 1} of {STEPS.length}
          </span>
          {stepIdx < STEPS.length - 1 && (
            <button
              onClick={() => STEPS[stepIdx + 1] && goTo(STEPS[stepIdx + 1]!.key)}
              className="flex items-center gap-1 text-txt-secondary hover:text-txt-primary"
            >
              Next <ChevronRight size={12} />
            </button>
          )}
        </div>
      </div>
    </Dialog>
  );
}

export default OnboardingWizard;

// ─────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────

function isStepComplete(key: StepKey, s: OnboardingStatus): boolean {
  switch (key) {
    case 'comfyui':
      return s.comfyui_servers > 0;
    case 'llm':
      return s.llm_configs > 0;
    case 'voice':
      return s.voice_profiles > 0;
    case 'youtube':
      return s.youtube_channels > 0;
  }
}

// ─────────────────────────────────────────────────────────────────
// Step 1 — ComfyUI
// ─────────────────────────────────────────────────────────────────

function ComfyUIStep({
  done,
  onSaved,
  onSkip,
}: {
  done: boolean;
  onSaved: () => void | Promise<void>;
  onSkip: () => void;
}) {
  const { toast } = useToast();
  const [name, setName] = useState('Local');
  const [url, setUrl] = useState('http://host.docker.internal:8188');
  const [submitting, setSubmitting] = useState(false);

  const submit = async () => {
    setSubmitting(true);
    try {
      await comfyuiServers.create({
        name,
        url,
        max_concurrent: 2,
        is_active: true,
      });
      toast.success('ComfyUI server saved', { description: name });
      await onSaved();
    } catch (err) {
      toast.error('Could not save ComfyUI server', { description: formatError(err) });
    } finally {
      setSubmitting(false);
    }
  };

  if (done) {
    return (
      <StepDone
        title="ComfyUI is connected."
        body="You can tune servers or add more workflows any time from Settings → ComfyUI."
      />
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <h3 className="font-semibold text-base mb-1">Connect your ComfyUI server</h3>
        <p className="text-sm text-txt-secondary">
          ComfyUI runs outside Drevalis and handles scene image + video generation. Default URL
          works if you're running ComfyUI on the same host as Docker Desktop.
        </p>
      </div>

      <div>
        <label className="text-xs text-txt-secondary block mb-1">Display name</label>
        <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Local" />
      </div>
      <div>
        <label className="text-xs text-txt-secondary block mb-1">URL</label>
        <Input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="http://host.docker.internal:8188"
          className="font-mono text-sm"
        />
        <p className="text-[11px] text-txt-muted mt-1">
          Linux / local-dev alternative: <code className="font-mono">http://localhost:8188</code>
        </p>
      </div>

      <StepActions
        onPrimary={submit}
        onSkip={onSkip}
        primaryLabel={submitting ? 'Saving…' : 'Save + continue'}
        primaryDisabled={submitting || !url.trim()}
        skipLabel="Set up later"
      />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// Step 2 — LLM
// ─────────────────────────────────────────────────────────────────

type LLMPreset = 'lm_studio' | 'ollama' | 'anthropic' | 'openai_custom';

const LLM_PRESETS: Record<
  LLMPreset,
  { name: string; baseUrl: string; model: string; needsKey: boolean }
> = {
  lm_studio: {
    name: 'LM Studio',
    baseUrl: 'http://host.docker.internal:1234/v1',
    model: 'local-model',
    needsKey: false,
  },
  ollama: {
    name: 'Ollama',
    baseUrl: 'http://host.docker.internal:11434/v1',
    model: 'llama3',
    needsKey: false,
  },
  anthropic: {
    name: 'Claude (Anthropic)',
    baseUrl: 'https://api.anthropic.com',
    model: 'claude-sonnet-4-20250514',
    needsKey: true,
  },
  openai_custom: {
    name: 'Custom OpenAI-compatible',
    baseUrl: '',
    model: '',
    needsKey: false,
  },
};

function LLMStep({
  done,
  onSaved,
  onSkip,
}: {
  done: boolean;
  onSaved: () => void | Promise<void>;
  onSkip: () => void;
}) {
  const { toast } = useToast();
  const [preset, setPreset] = useState<LLMPreset>('lm_studio');
  const [name, setName] = useState('LM Studio');
  const [baseUrl, setBaseUrl] = useState(LLM_PRESETS.lm_studio.baseUrl);
  const [model, setModel] = useState(LLM_PRESETS.lm_studio.model);
  const [apiKey, setApiKey] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const applyPreset = (p: LLMPreset) => {
    setPreset(p);
    const preset = LLM_PRESETS[p];
    setName(preset.name);
    setBaseUrl(preset.baseUrl);
    setModel(preset.model);
    setApiKey('');
  };

  const submit = async () => {
    const p = LLM_PRESETS[preset];
    setSubmitting(true);
    try {
      await llmConfigs.create({
        name,
        base_url: baseUrl,
        model_name: model,
        api_key: p.needsKey ? apiKey : undefined,
      });
      toast.success('LLM endpoint saved', { description: name });
      await onSaved();
    } catch (err) {
      toast.error('Could not save LLM endpoint', { description: formatError(err) });
    } finally {
      setSubmitting(false);
    }
  };

  if (done) {
    return (
      <StepDone
        title="LLM endpoint configured."
        body="Add more endpoints or tweak settings from Settings → LLM. Multiple endpoints round-robin automatically."
      />
    );
  }

  const p = LLM_PRESETS[preset];

  return (
    <div className="space-y-4">
      <div>
        <h3 className="font-semibold text-base mb-1">Pick an LLM endpoint</h3>
        <p className="text-sm text-txt-secondary">
          The LLM writes your scripts. Local options need nothing. Claude needs a paid Anthropic
          API key — your key, your bill.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-2">
        {(Object.keys(LLM_PRESETS) as LLMPreset[]).map((key) => (
          <button
            key={key}
            onClick={() => applyPreset(key)}
            className={`
              p-3 rounded-md border text-left text-sm font-medium transition-colors
              ${
                preset === key
                  ? 'border-accent/40 bg-accent/10 text-accent'
                  : 'border-white/[0.08] bg-bg-elevated text-txt-primary hover:border-white/[0.15]'
              }
            `}
          >
            {LLM_PRESETS[key].name}
          </button>
        ))}
      </div>

      <div>
        <label className="text-xs text-txt-secondary block mb-1">Display name</label>
        <Input value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div>
        <label className="text-xs text-txt-secondary block mb-1">Base URL</label>
        <Input
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          className="font-mono text-sm"
        />
      </div>
      <div>
        <label className="text-xs text-txt-secondary block mb-1">Model</label>
        <Input
          value={model}
          onChange={(e) => setModel(e.target.value)}
          className="font-mono text-sm"
          placeholder="local-model"
        />
      </div>
      {p.needsKey && (
        <div>
          <label className="text-xs text-txt-secondary block mb-1">API key</label>
          <Input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="sk-ant-..."
          />
          <p className="text-[11px] text-txt-muted mt-1">
            Stored Fernet-encrypted at rest — never leaves your install.
          </p>
        </div>
      )}

      <StepActions
        onPrimary={submit}
        onSkip={onSkip}
        primaryLabel={submitting ? 'Saving…' : 'Save + continue'}
        primaryDisabled={
          submitting || !name.trim() || !baseUrl.trim() || !model.trim() || (p.needsKey && !apiKey.trim())
        }
        skipLabel="Set up later"
      />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// Step 3 — Voice
// ─────────────────────────────────────────────────────────────────

const VOICE_STARTERS: {
  name: string;
  provider: 'edge';
  edge_voice_id: string;
  gender: string;
}[] = [
  { name: 'Aria (US English, female)', provider: 'edge', edge_voice_id: 'en-US-AriaNeural', gender: 'female' },
  { name: 'Guy (US English, male)', provider: 'edge', edge_voice_id: 'en-US-GuyNeural', gender: 'male' },
  { name: 'Jenny (US English, female)', provider: 'edge', edge_voice_id: 'en-US-JennyNeural', gender: 'female' },
  { name: 'Davis (US English, male)', provider: 'edge', edge_voice_id: 'en-US-DavisNeural', gender: 'male' },
];

function VoiceStep({
  done,
  onSaved,
  onSkip,
}: {
  done: boolean;
  onSaved: () => void | Promise<void>;
  onSkip: () => void;
}) {
  const { toast } = useToast();
  const [picked, setPicked] = useState<string>(VOICE_STARTERS[0]!.name);
  const [submitting, setSubmitting] = useState(false);

  const submit = async () => {
    const v = VOICE_STARTERS.find((x) => x.name === picked);
    if (!v) return;
    setSubmitting(true);
    try {
      await voiceProfiles.create({
        name: v.name,
        provider: v.provider,
        edge_voice_id: v.edge_voice_id,
        gender: v.gender,
        speed: 1.0,
        pitch: 1.0,
      });
      toast.success('Voice profile saved', { description: v.name });
      await onSaved();
    } catch (err) {
      toast.error('Could not save voice profile', { description: formatError(err) });
    } finally {
      setSubmitting(false);
    }
  };

  if (done) {
    return (
      <StepDone
        title="You have a default voice."
        body="Add more voices — Piper, Kokoro, ElevenLabs — any time from Settings → Voices."
      />
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <h3 className="font-semibold text-base mb-1">Pick a starter voice</h3>
        <p className="text-sm text-txt-secondary">
          Microsoft Edge neural voices are free and require no setup. Swap in Kokoro, Piper, or
          ElevenLabs later.
        </p>
      </div>

      <div className="space-y-2">
        {VOICE_STARTERS.map((v) => (
          <label
            key={v.name}
            className={`
              flex items-center gap-3 p-3 rounded-md border cursor-pointer transition-colors
              ${
                picked === v.name
                  ? 'border-accent/40 bg-accent/10'
                  : 'border-white/[0.08] bg-bg-elevated hover:border-white/[0.15]'
              }
            `}
          >
            <input
              type="radio"
              name="starter-voice"
              value={v.name}
              checked={picked === v.name}
              onChange={() => setPicked(v.name)}
              className="accent-accent"
            />
            <div className="flex-1">
              <div className="text-sm font-medium text-txt-primary">{v.name}</div>
              <div className="text-[11px] font-mono text-txt-muted">{v.edge_voice_id}</div>
            </div>
          </label>
        ))}
      </div>

      <StepActions
        onPrimary={submit}
        onSkip={onSkip}
        primaryLabel={submitting ? 'Saving…' : 'Save + continue'}
        primaryDisabled={submitting}
        skipLabel="Set up later"
      />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// Step 4 — YouTube (optional)
// ─────────────────────────────────────────────────────────────────

function YouTubeStep({
  done,
  onSkip,
  onDone,
}: {
  done: boolean;
  onSkip: () => void;
  onDone: () => void;
}) {
  if (done) {
    return (
      <StepDone
        title="YouTube is connected."
        body="Upload settings per channel live in Settings → YouTube. Studio tier also unlocks TikTok and Instagram."
      />
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <h3 className="font-semibold text-base mb-1">Connect YouTube (optional)</h3>
        <p className="text-sm text-txt-secondary">
          Auto-uploads finished episodes. You can also export the MP4 and upload by hand. Connect
          later from Settings → YouTube if you'd rather skip now.
        </p>
      </div>

      <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3 flex gap-3">
        <AlertCircle className="text-amber-400 shrink-0 mt-0.5" size={16} />
        <p className="text-xs text-amber-200 leading-relaxed">
          You'll also need a Google Cloud OAuth client configured in Settings → YouTube first
          (one-time setup, ~5 minutes — instructions in the docs).
        </p>
      </div>

      <div className="flex items-center justify-between pt-2">
        <Button variant="ghost" onClick={onSkip}>
          Skip for now
        </Button>
        <Button variant="primary" onClick={onDone}>
          I'll do this later
        </Button>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// Shared step UI bits
// ─────────────────────────────────────────────────────────────────

function StepDone({ title, body }: { title: string; body: string }) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-10">
      <div className="w-12 h-12 rounded-full bg-accent/15 border border-accent/30 flex items-center justify-center mb-4">
        <Check className="text-accent" size={22} />
      </div>
      <h3 className="font-semibold text-base mb-2">{title}</h3>
      <p className="text-sm text-txt-secondary max-w-md">{body}</p>
    </div>
  );
}

function StepActions({
  onPrimary,
  onSkip,
  primaryLabel,
  primaryDisabled,
  skipLabel,
}: {
  onPrimary: () => void | Promise<void>;
  onSkip: () => void;
  primaryLabel: string;
  primaryDisabled?: boolean;
  skipLabel: string;
}) {
  return (
    <div className="flex items-center justify-between pt-2">
      <Button variant="ghost" onClick={onSkip}>
        {skipLabel}
      </Button>
      <Button variant="primary" onClick={() => void onPrimary()} disabled={primaryDisabled}>
        {primaryLabel}
      </Button>
    </div>
  );
}
