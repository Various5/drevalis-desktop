import {
  Play,
  RotateCcw,
  Square,
  RefreshCw,
  Mic,
  Scissors,
  ListChecks,
  Copy,
  Trash2,
  ChevronDown,
  MoreHorizontal,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import * as Popover from '@radix-ui/react-popover';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { JobProgressBar } from '@/components/jobs/JobProgressBar';
import { Loader2 } from 'lucide-react';
import type { Episode, ProgressMessage, PipelineStep } from '@/types';

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface ActionBarProps {
  episode: Episode;
  action: ActionKind;
  mergedProgress: Record<string, ProgressMessage>;
  onGenerate: (steps?: PipelineStep[]) => void;
  onRetry: () => void;
  onReassemble: () => void;
  onRegenerateVoice: () => void;
  onDuplicate: () => void;
  onReset: () => void;
  onOpenCancel: () => void;
  onOpenDelete: () => void;
}

/** Discriminated union aligned with the parent ActionState. */
export type ActionKind =
  | 'idle'
  | 'generating'
  | 'retrying'
  | 'reassembling'
  | 'revoicing'
  | 'duplicating'
  | 'resetting'
  | 'cancelling'
  | 'deleting'
  | 'uploading'
  | 'scheduling'
  | 'publishingAll'
  | 'generatingSeo';

const STEP_ORDER = [
  'script',
  'voice',
  'scenes',
  'captions',
  'assembly',
  'thumbnail',
] as const;

const STEP_ETA: Record<string, string> = {
  script: '~10s',
  voice: '~30s',
  scenes: '~2-5 min',
  captions: '~20s',
  assembly: '~30s',
  thumbnail: '~10s',
};

// ---------------------------------------------------------------------------
// RegenerateMenu — dropdown for post-generation regen options
// ---------------------------------------------------------------------------

interface RegenerateMenuProps {
  episodeId: string;
  action: ActionKind;
  onReassemble: () => void;
  onRegenerateVoice: () => void;
  onGenerate: (steps?: PipelineStep[]) => void;
}

function RegenerateMenu({
  episodeId,
  action,
  onReassemble,
  onRegenerateVoice,
  onGenerate,
}: RegenerateMenuProps) {
  const navigate = useNavigate();
  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <Button variant="primary" size="sm" aria-label="Regenerate options">
          <RefreshCw size={14} />
          Regenerate
          <ChevronDown size={12} />
        </Button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="start"
          sideOffset={4}
          className="w-52 bg-bg-surface border border-border rounded-lg shadow-xl z-[50] py-1 animate-fade-in"
        >
          <Popover.Close asChild>
            <button
              type="button"
              onClick={() => onGenerate()}
              disabled={action !== 'idle'}
              className="w-full flex items-center gap-2 px-3 py-2 text-sm text-txt-primary hover:bg-bg-hover disabled:opacity-50"
            >
              <Play size={14} />
              Full regeneration
            </button>
          </Popover.Close>
          <Popover.Close asChild>
            <button
              type="button"
              onClick={() => onGenerate(['voice', 'captions', 'assembly', 'thumbnail'])}
              disabled={action !== 'idle'}
              className="w-full flex items-center gap-2 px-3 py-2 text-sm text-txt-primary hover:bg-bg-hover disabled:opacity-50"
            >
              <Mic size={14} />
              Re-voice
            </button>
          </Popover.Close>
          <Popover.Close asChild>
            <button
              type="button"
              onClick={() => onGenerate(['scenes', 'captions', 'assembly', 'thumbnail'])}
              disabled={action !== 'idle'}
              className="w-full flex items-center gap-2 px-3 py-2 text-sm text-txt-primary hover:bg-bg-hover disabled:opacity-50"
            >
              <RefreshCw size={14} />
              Regenerate scenes
            </button>
          </Popover.Close>
          <Popover.Close asChild>
            <button
              type="button"
              onClick={() => onGenerate(['captions', 'assembly'])}
              disabled={action !== 'idle'}
              className="w-full flex items-center gap-2 px-3 py-2 text-sm text-txt-primary hover:bg-bg-hover disabled:opacity-50"
            >
              <RefreshCw size={14} />
              Regenerate captions
            </button>
          </Popover.Close>
          <Popover.Close asChild>
            <button
              type="button"
              onClick={() => onGenerate(['thumbnail'])}
              disabled={action !== 'idle'}
              className="w-full flex items-center gap-2 px-3 py-2 text-sm text-txt-primary hover:bg-bg-hover disabled:opacity-50"
            >
              <RefreshCw size={14} />
              Regenerate thumbnail
            </button>
          </Popover.Close>
          <div className="my-1 border-t border-border" />
          <Popover.Close asChild>
            <button
              type="button"
              onClick={() => onReassemble()}
              disabled={action !== 'idle'}
              className="w-full flex items-center gap-2 px-3 py-2 text-sm text-txt-primary hover:bg-bg-hover disabled:opacity-50"
            >
              <RefreshCw size={14} />
              {action === 'reassembling' ? 'Reassembling…' : 'Reassemble'}
            </button>
          </Popover.Close>
          <Popover.Close asChild>
            <button
              type="button"
              onClick={() => onRegenerateVoice()}
              disabled={action !== 'idle'}
              className="w-full flex items-center gap-2 px-3 py-2 text-sm text-txt-primary hover:bg-bg-hover disabled:opacity-50"
            >
              <Mic size={14} />
              {action === 'revoicing' ? 'Re-voicing…' : 'Re-voice (keep scenes)'}
            </button>
          </Popover.Close>
          <div className="my-1 border-t border-border" />
          <Popover.Close asChild>
            <button
              type="button"
              onClick={() => navigate(`/episodes/${episodeId}/edit`)}
              className="w-full flex items-center gap-2 px-3 py-2 text-sm text-txt-primary hover:bg-bg-hover"
            >
              <Scissors size={14} />
              Open in editor
            </button>
          </Popover.Close>
          <Popover.Close asChild>
            <button
              type="button"
              onClick={() => navigate(`/episodes/${episodeId}/shot-list`)}
              className="w-full flex items-center gap-2 px-3 py-2 text-sm text-txt-primary hover:bg-bg-hover"
            >
              <ListChecks size={14} />
              Open shot list
            </button>
          </Popover.Close>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

// ---------------------------------------------------------------------------
// OverflowMenu — secondary / destructive actions behind ⋮
// ---------------------------------------------------------------------------

interface OverflowMenuProps {
  episode: Episode;
  action: ActionKind;
  onDuplicate: () => void;
  onReset: () => void;
  onOpenDelete: () => void;
}

function OverflowMenu({
  episode,
  action,
  onDuplicate,
  onReset,
  onOpenDelete,
}: OverflowMenuProps) {
  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <Button
          variant="secondary"
          size="sm"
          aria-label="More actions"
          aria-haspopup="menu"
        >
          <MoreHorizontal size={14} />
        </Button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="end"
          sideOffset={4}
          className="w-52 bg-bg-surface border border-border rounded-lg shadow-xl z-[50] py-1 animate-fade-in"
        >
          <Popover.Close asChild>
            <button
              type="button"
              onClick={() => onDuplicate()}
              disabled={action !== 'idle'}
              className="w-full flex items-center gap-2 px-3 py-2 text-sm text-txt-primary hover:bg-bg-hover disabled:opacity-50"
            >
              <Copy size={14} />
              {action === 'duplicating' ? 'Duplicating…' : 'Duplicate'}
            </button>
          </Popover.Close>
          {episode.status !== 'draft' && (
            <Popover.Close asChild>
              <button
                type="button"
                onClick={() => onReset()}
                disabled={action !== 'idle'}
                className="w-full flex items-center gap-2 px-3 py-2 text-sm text-txt-primary hover:bg-bg-hover disabled:opacity-50"
              >
                <RotateCcw size={14} />
                {action === 'resetting' ? 'Resetting…' : 'Reset to draft'}
              </button>
            </Popover.Close>
          )}
          <div className="my-1 border-t border-border" />
          <Popover.Close asChild>
            <button
              type="button"
              onClick={() => onOpenDelete()}
              className="w-full flex items-center gap-2 px-3 py-2 text-sm text-error hover:bg-bg-hover"
            >
              <Trash2 size={14} />
              Delete
            </button>
          </Popover.Close>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

// ---------------------------------------------------------------------------
// ActionBar — sticky banner
// ---------------------------------------------------------------------------

export function ActionBar({
  episode,
  action,
  mergedProgress,
  onGenerate,
  onRetry,
  onReassemble,
  onRegenerateVoice,
  onDuplicate,
  onReset,
  onOpenCancel,
  onOpenDelete,
}: ActionBarProps) {
  const isGenerating = episode.status === 'generating';
  const canGenerate =
    episode.status === 'draft' || episode.status === 'failed';
  const isPostGeneration =
    episode.status === 'review' ||
    episode.status === 'editing' ||
    episode.status === 'exported';

  // Per-step progress summary for the inline progress bar
  const activeEntry = STEP_ORDER.map(
    (s) => [s, mergedProgress[s]] as const,
  ).find(([, msg]) => msg?.status === 'running');
  const activeStepName = activeEntry?.[0] ?? null;
  const activeMsg = activeEntry?.[1] ?? null;
  const overallPct = Math.round(
    STEP_ORDER.reduce((sum, s) => {
      const m = mergedProgress[s];
      if (!m) return sum;
      return sum + (m.status === 'done' ? 100 : (m.progress_pct ?? 0));
    }, 0) / STEP_ORDER.length,
  );

  return (
    <div
      className="sticky top-0 z-30 bg-bg-surface/95 backdrop-blur-sm border-b border-border"
      role="toolbar"
      aria-label="Episode actions"
    >
      {/* Title + status + action buttons row */}
      <div className="flex items-center gap-2 px-4 py-2.5 min-h-[52px]">
        {/* Left: title + status pill */}
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <h1 className="text-base font-bold text-txt-primary truncate">
            {episode.title}
          </h1>
          <Badge variant={episode.status} dot>
            {episode.status}
          </Badge>
        </div>

        {/* Right: primary action + overflow */}
        <div className="flex items-center gap-1.5 shrink-0">
          {/* draft / failed → Generate / Retry */}
          {canGenerate && episode.status === 'draft' && (
            <Button
              variant="primary"
              size="sm"
              loading={action === 'generating'}
              onClick={() => onGenerate()}
            >
              <Play size={14} />
              Generate
            </Button>
          )}
          {canGenerate && episode.status === 'failed' && (
            <Button
              variant="primary"
              size="sm"
              loading={action === 'retrying'}
              onClick={() => onRetry()}
            >
              <RotateCcw size={14} />
              Retry generation
            </Button>
          )}

          {/* generating → Stop */}
          {isGenerating && (
            <Button
              variant="ghost"
              size="sm"
              className="text-error hover:text-error/80"
              loading={action === 'cancelling'}
              onClick={() => onOpenCancel()}
            >
              <Square size={14} />
              Stop
            </Button>
          )}

          {/* review / editing / exported → Regenerate dropdown */}
          {isPostGeneration && (
            <RegenerateMenu
              episodeId={episode.id}
              action={action}
              onReassemble={onReassemble}
              onRegenerateVoice={onRegenerateVoice}
              onGenerate={onGenerate}
            />
          )}

          {/* Always-visible overflow for secondary / destructive actions */}
          <OverflowMenu
            episode={episode}
            action={action}
            onDuplicate={onDuplicate}
            onReset={onReset}
            onOpenDelete={onOpenDelete}
          />
        </div>
      </div>

      {/* Inline progress strip — only while generating */}
      {isGenerating && (
        <div
          className="px-4 pb-3"
          aria-live="polite"
          aria-busy="true"
          aria-label="Generation progress"
        >
          <div className="flex items-center gap-2 mb-1.5">
            <Loader2 size={13} className="text-accent animate-spin shrink-0" />
            <span className="text-xs font-medium text-txt-primary capitalize">
              {activeStepName
                ? `Generating: ${activeStepName}`
                : 'Generation in progress…'}
            </span>
            {activeStepName && (
              <span className="text-[11px] text-txt-tertiary ml-1">
                ETA {STEP_ETA[activeStepName] ?? '…'}
              </span>
            )}
            <span className="ml-auto text-xs font-mono font-bold text-accent tabular-nums">
              {overallPct}%
            </span>
          </div>
          {activeMsg?.message && (
            <p className="text-[11px] text-txt-secondary truncate mb-1.5">
              {activeMsg.message}
            </p>
          )}
          <JobProgressBar
            stepProgress={mergedProgress}
          />
        </div>
      )}
    </div>
  );
}
