import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { CheckCircle2, Circle, X, ArrowRight } from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import {
  comfyuiServers,
  llmConfigs,
  voiceProfiles,
  series as seriesApi,
  ApiError,
} from '@/lib/api';

/**
 * Onboarding checklist. Shows on the Dashboard until every step is done
 * OR the user dismisses it.  Dismissal is remembered via localStorage
 * so a power user isn't nagged every visit.
 */

const DISMISS_KEY = 'drevalis_setup_checklist_dismissed';

interface Step {
  id: string;
  label: string;
  description: string;
  done: boolean;
  goTo: string;
  cta: string;
}

export function SetupChecklist() {
  const navigate = useNavigate();
  const [steps, setSteps] = useState<Step[] | null>(null);
  const [dismissed, setDismissed] = useState<boolean>(
    () => localStorage.getItem(DISMISS_KEY) === '1',
  );

  useEffect(() => {
    if (dismissed) return;
    let cancelled = false;
    (async () => {
      try {
        const [servers, llms, voices, seriesList] = await Promise.allSettled([
          comfyuiServers.list(),
          llmConfigs.list(),
          voiceProfiles.list(),
          seriesApi.list(),
        ]);
        // If any call 402's (license gate), bail - LicenseGate owns that view.
        const anyGated = [servers, llms, voices, seriesList].some(
          (r) => r.status === 'rejected' && r.reason instanceof ApiError && r.reason.status === 402,
        );
        if (anyGated || cancelled) return;
        const val = <T,>(r: PromiseSettledResult<T[]>): T[] =>
          r.status === 'fulfilled' ? r.value : [];
        const checklist: Step[] = [
          {
            id: 'comfyui',
            label: 'Connect a ComfyUI server',
            description: 'Required for scene image / video generation.',
            done: val(servers).length > 0,
            goTo: '/settings',
            cta: 'Add server',
          },
          {
            id: 'llm',
            label: 'Configure an LLM endpoint',
            description: 'LM Studio, Ollama, vLLM, or an API-compatible model.',
            done: val(llms).length > 0,
            goTo: '/settings',
            cta: 'Add LLM',
          },
          {
            id: 'voice',
            label: 'Create a voice profile',
            description: 'Pick a TTS voice - Edge is free, no API key needed.',
            done: val(voices).length > 0,
            goTo: '/settings',
            cta: 'Add voice',
          },
          {
            id: 'series',
            label: 'Create your first series',
            description: 'Define a topic, tone, and visual style for your content.',
            done: val(seriesList).length > 0,
            goTo: '/series',
            cta: 'Create series',
          },
        ];
        if (!cancelled) setSteps(checklist);
      } catch {
        /* ignore - checklist is best-effort */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [dismissed]);

  if (dismissed) return null;
  if (!steps) return null;

  const doneCount = steps.filter((s) => s.done).length;
  if (doneCount === steps.length) return null; // all done, hide

  const dismiss = () => {
    localStorage.setItem(DISMISS_KEY, '1');
    setDismissed(true);
  };

  return (
    <Card className="p-5 border-accent/30 bg-accent/[0.04]">
      <div className="flex items-start justify-between gap-3 mb-4">
        <div>
          <h3 className="font-semibold text-lg flex items-center gap-2">
            Getting started
            <span className="text-xs font-normal text-txt-muted">
              {doneCount} of {steps.length} complete
            </span>
          </h3>
          <p className="text-sm text-txt-secondary mt-0.5">
            Finish these once - your series will then be three clicks away from a finished video.
          </p>
        </div>
        <button
          onClick={dismiss}
          className="text-txt-muted hover:text-txt-primary"
          aria-label="Dismiss setup checklist"
          title="Dismiss - you can always follow the Help page later"
        >
          <X size={18} />
        </button>
      </div>
      <div className="space-y-2">
        {steps.map((s) => (
          <div
            key={s.id}
            className="flex items-center justify-between gap-3 p-3 rounded bg-bg-elevated/50"
          >
            <div className="flex items-start gap-3 min-w-0">
              {s.done ? (
                <CheckCircle2 className="text-accent shrink-0 mt-0.5" size={18} />
              ) : (
                <Circle className="text-txt-muted shrink-0 mt-0.5" size={18} />
              )}
              <div className="min-w-0">
                <div
                  className={
                    s.done
                      ? 'text-sm text-txt-muted line-through'
                      : 'text-sm text-txt-primary font-medium'
                  }
                >
                  {s.label}
                </div>
                <div className="text-xs text-txt-muted">{s.description}</div>
              </div>
            </div>
            {!s.done && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => navigate(s.goTo)}
                className="shrink-0"
              >
                {s.cta}
                <ArrowRight className="w-3.5 h-3.5 ml-1" />
              </Button>
            )}
          </div>
        ))}
      </div>
    </Card>
  );
}
