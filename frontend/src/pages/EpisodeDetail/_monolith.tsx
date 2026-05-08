import {
  useState,
  useEffect,
  useCallback,
  useMemo,
  useRef,
  lazy,
  Suspense,
} from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  FileText,
  ImageIcon,
  Subtitles,
  Info,
  AlertTriangle,
  RefreshCw,
  Download,
  Film,
  Archive,
  Upload,
  ChevronDown,
  Music,
  Loader2,
  Trash2,
} from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { Card } from '@/components/ui/Card';
import { Input, Textarea } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { Dialog, DialogFooter } from '@/components/ui/Dialog';
import { ThumbnailEditor } from '@/components/episode/ThumbnailEditor';
import { Spinner } from '@/components/ui/Spinner';
import { VideoPlayer } from '@/components/video/VideoPlayer';
import * as Popover from '@radix-ui/react-popover';
import { Breadcrumb } from '@/components/ui/Breadcrumb';
import {
  episodes as episodesApi,
  youtube as youtubeApi,
  voiceProfiles as voiceProfilesApi,
  schedule as scheduleApi,
} from '@/lib/api';
import { useToast } from '@/components/ui/Toast';
import { useEpisodeProgress } from '@/lib/websocket';
import { useDocumentTitle } from '@/hooks/useDocumentTitle';
import type {
  Episode,
  MediaAsset,
  PipelineStep,
  YouTubeUploadRequest,
  VoiceProfile,
} from '@/types';
import type { SceneDataExtended } from './sections/helpers';
import { ActionBar } from './sections/ActionBar';
import { PublishRow } from './sections/PublishRow';
import { EpisodeSidebar } from './sections/EpisodeSidebar';

// ---------------------------------------------------------------------------
// Lazy-loaded tab components
// ---------------------------------------------------------------------------

const ScriptTab = lazy(() =>
  import('./sections/ScriptTab').then((m) => ({ default: m.ScriptTab })),
);
const ScenesTab = lazy(() =>
  import('./sections/ScenesTab').then((m) => ({ default: m.ScenesTab })),
);
const CaptionsTab = lazy(() =>
  import('./sections/CaptionsTab').then((m) => ({ default: m.CaptionsTab })),
);
const MusicTab = lazy(() =>
  import('./sections/MusicTab').then((m) => ({ default: m.MusicTab })),
);
const MetadataTab = lazy(() =>
  import('./sections/MetadataTab').then((m) => ({ default: m.MetadataTab })),
);

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------

const TABS = [
  { id: 'script', label: 'Script', icon: FileText },
  { id: 'scenes', label: 'Scenes', icon: ImageIcon },
  { id: 'captions', label: 'Captions', icon: Subtitles },
  { id: 'music', label: 'Music', icon: Music },
  { id: 'metadata', label: 'Metadata', icon: Info },
] as const;

type TabId = (typeof TABS)[number]['id'];

// ---------------------------------------------------------------------------
// Action state — discriminated union replaces 12 separate booleans
// ---------------------------------------------------------------------------

type ActionState =
  | { kind: 'idle' }
  | { kind: 'generating' }
  | { kind: 'retrying' }
  | { kind: 'reassembling' }
  | { kind: 'revoicing' }
  | { kind: 'duplicating' }
  | { kind: 'resetting' }
  | { kind: 'cancelling' }
  | { kind: 'deleting' }
  | { kind: 'uploading' }
  | { kind: 'scheduling' }
  | { kind: 'publishingAll' }
  | { kind: 'generatingSeo' };

// ---------------------------------------------------------------------------
// Episode Detail Page
// ---------------------------------------------------------------------------

function EpisodeDetail() {
  const { episodeId } = useParams<{ episodeId: string }>();
  const navigate = useNavigate();

  const [episode, setEpisode] = useState<Episode | null>(null);
  const [loading, setLoading] = useState(true);

  useDocumentTitle(episode?.title ?? 'Episode Detail');
  const prevEpisodeStatusRef = useRef<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabId>('script');

  // Single discriminated-union for all mutually-exclusive action states
  const [action, setAction] = useState<ActionState>({ kind: 'idle' });

  const [cancelDialogOpen, setCancelDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);

  // Voice profiles and per-episode overrides
  const [voiceProfiles, setVoiceProfiles] = useState<VoiceProfile[]>([]);
  const [epVoiceId, setEpVoiceId] = useState<string>('');
  const [epCaptionStyle, setEpCaptionStyle] = useState<string>('');

  // YouTube upload state
  const [youtubeConnected, setYoutubeConnected] = useState(false);
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false);
  const [thumbEditorOpen, setThumbEditorOpen] = useState(false);
  const [publishAllOpen, setPublishAllOpen] = useState(false);
  const [publishAllPlatforms, setPublishAllPlatforms] = useState<
    Record<'youtube' | 'tiktok' | 'instagram', boolean>
  >({ youtube: true, tiktok: true, instagram: true });
  const [ytTitle, setYtTitle] = useState('');
  const [ytDescription, setYtDescription] = useState('');
  const [ytTags, setYtTags] = useState('');
  const [ytPrivacy, setYtPrivacy] = useState('public');

  // Schedule dialog state
  const [scheduleDialogOpen, setScheduleDialogOpen] = useState(false);
  const [schedPlatform, setSchedPlatform] = useState('youtube');
  const [schedDatetime, setSchedDatetime] = useState('');
  const [schedTitle, setSchedTitle] = useState('');
  const [schedPrivacy, setSchedPrivacy] = useState('public');

  // SEO dialog state
  const [seoOpen, setSeoOpen] = useState(false);
  const [seoData, setSeoData] = useState<{
    title: string;
    description: string;
    hashtags: string[];
    tags: string[];
    hook: string;
    virality_score?: number;
  } | null>(null);

  // Toast notifications
  const { toast } = useToast();

  // WebSocket progress
  const { latestByStep } = useEpisodeProgress(
    episode?.status === 'generating' ? episodeId : null,
  );

  // Fetch episode data
  const fetchEpisode = useCallback(async () => {
    if (!episodeId) return;
    try {
      const ep = await episodesApi.get(episodeId);
      const previousStatus = prevEpisodeStatusRef.current;
      prevEpisodeStatusRef.current = ep.status;
      setEpisode(ep);
      // Auto-generate SEO when generation completes and no SEO data yet
      if (
        previousStatus === 'generating' &&
        ep.status === 'review' &&
        !(ep.metadata_?.seo)
      ) {
        episodesApi
          .generateSeo(episodeId)
          .then((seoResult) => {
            return episodesApi.update(episodeId, {
              metadata_: {
                ...((ep.metadata_ as Record<string, unknown>) ?? {}),
                seo: seoResult,
              },
            } as any);
          })
          .catch(() => {
            // Non-fatal
          });
      }
    } catch (err) {
      toast.error('Failed to load episode', { description: String(err) });
    } finally {
      setLoading(false);
    }
  }, [episodeId]);

  useEffect(() => {
    void fetchEpisode();
  }, [fetchEpisode]);

  // Refresh when generation completes (WebSocket-based)
  useEffect(() => {
    if (!episode || episode.status !== 'generating') return;
    const allDone = Object.values(latestByStep).every(
      (msg) => msg.status === 'done' || msg.status === 'failed',
    );
    if (allDone && Object.keys(latestByStep).length > 0) {
      const timer = setTimeout(() => void fetchEpisode(), 2000);
      return () => clearTimeout(timer);
    }
  }, [latestByStep, episode, fetchEpisode]);

  // Polling fallback: re-fetch every 3s while generating
  useEffect(() => {
    if (!episode || episode.status !== 'generating') return;
    const interval = setInterval(() => void fetchEpisode(), 3000);
    return () => clearInterval(interval);
  }, [episode?.status, fetchEpisode]);

  // Check YouTube connection status
  useEffect(() => {
    youtubeApi
      .getStatus()
      .then((res) => setYoutubeConnected(res.connected))
      .catch(() => setYoutubeConnected(false));
  }, []);

  // Load voice profiles on mount
  useEffect(() => {
    voiceProfilesApi.list().then(setVoiceProfiles).catch(() => {});
  }, []);

  // Sync per-episode overrides from episode data
  useEffect(() => {
    if (episode) {
      setEpVoiceId(episode.override_voice_profile_id ?? '');
      setEpCaptionStyle(episode.override_caption_style ?? '');
    }
  }, [episode]);

  // Pre-fill YouTube upload dialog from script metadata
  useEffect(() => {
    if (uploadDialogOpen && episode) {
      const script = (episode.script ?? {}) as Record<string, unknown>;
      setYtTitle((script['title'] as string) || episode.title || '');
      setYtDescription((script['description'] as string) || '');
      const hashtags = script['hashtags'] as string[] | undefined;
      setYtTags(
        Array.isArray(hashtags) && hashtags.length > 0
          ? hashtags.join(', ')
          : '',
      );
    }
  }, [uploadDialogOpen, episode]);

  // ---- Handlers ----

  const handleGenerate = async (steps?: PipelineStep[]) => {
    if (!episodeId) return;
    setAction({ kind: 'generating' });
    try {
      await episodesApi.generate(episodeId, steps ? { steps } : undefined);
      toast.success('Episode generation started');
      void fetchEpisode();
    } catch (err) {
      toast.error('Failed to start generation', { description: String(err) });
    } finally {
      setAction({ kind: 'idle' });
    }
  };

  const handleRetry = async () => {
    if (!episodeId) return;
    setAction({ kind: 'retrying' });
    try {
      await episodesApi.retry(episodeId);
      toast.success('Episode generation started');
      void fetchEpisode();
    } catch (err) {
      toast.error('Failed to retry generation', { description: String(err) });
    } finally {
      setAction({ kind: 'idle' });
    }
  };

  const handleRetryStep = async (step: PipelineStep) => {
    if (!episodeId) return;
    try {
      await episodesApi.retryStep(episodeId, step);
      toast.success('Episode generation started');
      void fetchEpisode();
    } catch (err) {
      toast.error(`Failed to retry step: ${step}`, {
        description: String(err),
      });
    }
  };

  const handleReassemble = async () => {
    if (!episodeId) return;
    setAction({ kind: 'reassembling' });
    try {
      await episodesApi.reassemble(episodeId);
      toast.success('Reassembly started');
      void fetchEpisode();
    } catch (err) {
      toast.error('Failed to reassemble episode', {
        description: String(err),
      });
    } finally {
      setAction({ kind: 'idle' });
    }
  };

  const handleRegenerateVoice = async () => {
    if (!episodeId) return;
    setAction({ kind: 'revoicing' });
    try {
      await episodesApi.regenerateVoice(episodeId, epVoiceId || undefined);
      toast.success('Voice regeneration started');
      void fetchEpisode();
    } catch (err) {
      toast.error('Failed to regenerate voice', { description: String(err) });
    } finally {
      setAction({ kind: 'idle' });
    }
  };

  const handleDuplicate = async () => {
    if (!episodeId) return;
    setAction({ kind: 'duplicating' });
    try {
      const dup = await episodesApi.duplicate(episodeId);
      navigate(`/episodes/${dup.id}`);
    } catch (err) {
      toast.error('Failed to duplicate episode', { description: String(err) });
    } finally {
      setAction({ kind: 'idle' });
    }
  };

  const handleReset = async () => {
    if (!episodeId) return;
    setAction({ kind: 'resetting' });
    try {
      await episodesApi.resetToDraft(episodeId);
      toast.success('Episode reset to draft');
      void fetchEpisode();
    } catch (err) {
      toast.error('Failed to reset episode', { description: String(err) });
    } finally {
      setAction({ kind: 'idle' });
    }
  };

  const handleCancel = async () => {
    if (!episodeId) return;
    setAction({ kind: 'cancelling' });
    try {
      await episodesApi.cancel(episodeId);
      setCancelDialogOpen(false);
      toast.success('Generation cancelled');
      void fetchEpisode();
    } catch (err) {
      toast.error('Failed to cancel generation', { description: String(err) });
    } finally {
      setAction({ kind: 'idle' });
    }
  };

  const handleDelete = async () => {
    if (!episodeId) return;
    setAction({ kind: 'deleting' });
    try {
      await episodesApi.delete(episodeId);
      navigate('/episodes');
    } catch (err) {
      toast.error('Failed to delete episode', { description: String(err) });
      setAction({ kind: 'idle' });
    }
  };

  const handleYouTubeUpload = async () => {
    if (!episodeId) return;
    setAction({ kind: 'uploading' });
    try {
      const data: YouTubeUploadRequest = {
        title: ytTitle,
        description: ytDescription,
        tags: ytTags
          .split(',')
          .map((t) => t.trim())
          .filter(Boolean),
        privacy_status: ytPrivacy as 'public' | 'unlisted' | 'private',
      };
      await youtubeApi.upload(episodeId, data);
      setUploadDialogOpen(false);
      toast.success('Upload to YouTube started');
    } catch (err) {
      toast.error('Failed to upload to YouTube', { description: String(err) });
    } finally {
      setAction({ kind: 'idle' });
    }
  };

  const handleSeo = async () => {
    if (!episodeId) return;
    setAction({ kind: 'generatingSeo' });
    try {
      const data = await episodesApi.generateSeo(episodeId);
      setSeoData(data);
      setSeoOpen(true);
      await episodesApi.update(episodeId, {
        metadata_: {
          ...((episode?.metadata_ as Record<string, unknown>) ?? {}),
          seo: data,
        },
      } as any);
      void fetchEpisode();
    } catch (err) {
      toast.error('Failed to generate SEO data', { description: String(err) });
    } finally {
      setAction({ kind: 'idle' });
    }
  };

  /** Open the schedule dialog pre-filled from the current episode. */
  const openScheduleDialog = () => {
    if (!episode) return;
    const script = (episode.script ?? {}) as Record<string, unknown>;
    const pad = (n: number) => String(n).padStart(2, '0');
    const now = new Date();
    now.setDate(now.getDate() + 1);
    now.setHours(12, 0, 0, 0);
    const iso = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T12:00`;
    setSchedDatetime(iso);
    setSchedTitle((script['title'] as string) || episode.title || '');
    setSchedPlatform('youtube');
    setSchedPrivacy('public');
    setScheduleDialogOpen(true);
  };

  // ---- Derived data ----

  const videoAsset = episode?.media_assets.find(
    (a: MediaAsset) => a.asset_type === 'video',
  );
  const videoUrl = videoAsset?.file_path
    ? `/storage/${videoAsset.file_path}`
    : null;
  const captionsAsset = episode?.media_assets.find(
    (a: MediaAsset) =>
      a.asset_type === 'caption' && a.file_path.endsWith('.srt'),
  );

  const scenes = useMemo<SceneDataExtended[]>(() => {
    if (!episode?.script) return [];
    const scriptData = episode.script as Record<string, unknown>;
    const segments = (scriptData['scenes'] ?? scriptData['segments']) as
      | Array<Record<string, unknown>>
      | undefined;
    if (!Array.isArray(segments)) return [];
    return segments.map((seg, idx) => {
      const sceneNum = idx + 1;
      const sceneAsset = episode.media_assets.find(
        (a: MediaAsset) =>
          a.asset_type === 'scene' && a.scene_number === sceneNum,
      );
      return {
        sceneNumber: sceneNum,
        imageUrl: sceneAsset?.file_path
          ? `/storage/${sceneAsset.file_path}`
          : null,
        prompt:
          (seg['visual_prompt'] as string) ??
          (seg['narration'] as string) ??
          '',
        durationSeconds: (seg['duration_seconds'] as number) ?? 3,
        narration:
          (seg['narration'] as string) ?? (seg['text'] as string) ?? '',
        visualPrompt: (seg['visual_prompt'] as string) ?? '',
        keywords: (seg['keywords'] as string[]) ?? [],
      };
    });
  }, [episode]);

  // Merge static job progress (DB) with real-time WS updates
  const jobStepProgress: Record<
    string,
    {
      status: string;
      progress_pct: number;
      message: string;
      step: string;
      job_id: string;
      episode_id: string;
      error: null;
      detail: null;
    }
  > = {};
  if (episode) {
    for (const job of episode.generation_jobs) {
      jobStepProgress[job.step] = {
        status: job.status,
        progress_pct: job.progress_pct,
        message: job.error_message ?? '',
        step: job.step,
        job_id: job.id,
        episode_id: episode.id,
        error: null,
        detail: null,
      };
    }
  }
  const mergedProgress = { ...jobStepProgress, ...latestByStep };

  const hasFailed = episode?.status === 'failed';

  // ---- Loading / not found guards ----

  if (loading) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <Spinner size="lg" />
      </div>
    );
  }

  if (!episode) {
    return (
      <div className="text-center py-20">
        <p className="text-txt-secondary">Episode not found</p>
        <Button variant="ghost" className="mt-4" onClick={() => navigate('/')}>
          Back to Dashboard
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-0">
      {/* Breadcrumb — above the sticky bar */}
      <Breadcrumb
        items={[
          { label: 'Episodes', to: '/episodes' },
          { label: episode.title || 'Episode' },
        ]}
        className="px-4 pt-3 pb-1"
      />

      {/* Sticky action bar (title + status + primary action + overflow) */}
      <ActionBar
        episode={episode}
        action={action.kind}
        mergedProgress={
          mergedProgress as Record<
            string,
            import('@/types').ProgressMessage
          >
        }
        onGenerate={(steps) => void handleGenerate(steps)}
        onRetry={() => void handleRetry()}
        onReassemble={() => void handleReassemble()}
        onRegenerateVoice={() => void handleRegenerateVoice()}
        onDuplicate={() => void handleDuplicate()}
        onReset={() => void handleReset()}
        onOpenCancel={() => setCancelDialogOpen(true)}
        onOpenDelete={() => setDeleteDialogOpen(true)}
      />

      {/* Error banner */}
      {hasFailed && (
        <div className="px-4 pt-3">
          <Card padding="md" className="border-error/30 bg-error-muted">
            <div className="flex items-start gap-3">
              <AlertTriangle size={18} className="text-error shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-medium text-error">
                  Generation failed
                </p>
                {episode.generation_jobs
                  .filter((j) => j.status === 'failed')
                  .map((j) => (
                    <div key={j.id} className="mt-1 flex items-center gap-2">
                      <Badge variant={j.step}>{j.step}</Badge>
                      <span className="text-xs text-error/80">
                        {j.error_message ?? 'Unknown error'}
                      </span>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() =>
                          void handleRetryStep(j.step as PipelineStep)
                        }
                      >
                        <RefreshCw size={12} />
                        Retry
                      </Button>
                    </div>
                  ))}
              </div>
            </div>
          </Card>
        </div>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Two-column layout: sidebar (left) + main column (right)            */}
      {/* Below lg: sidebar stacks above main column, no sticky              */}
      {/* ------------------------------------------------------------------ */}
      <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-6 px-4 pt-4 pb-8 items-start">
        {/* ---- Sidebar ---- */}
        <aside className="lg:sticky lg:top-[120px] flex flex-col">
          <EpisodeSidebar episode={episode} voiceProfiles={voiceProfiles} />
        </aside>

        {/* ---- Main column ---- */}
        <main className="flex flex-col gap-4 min-w-0">
          {/* Video player */}
          <VideoPlayer
            src={videoUrl}
            scenes={(() => {
              let cumTime = 0;
              return scenes.map((s) => {
                const seg = {
                  startTime: cumTime,
                  endTime: cumTime + s.durationSeconds,
                  label: `Scene ${s.sceneNumber}`,
                };
                cumTime += s.durationSeconds;
                return seg;
              });
            })()}
          />

          {/* Export popover — only when a video exists */}
          {videoUrl && (
            <div className="flex items-center justify-end">
              <Popover.Root>
                <Popover.Trigger asChild>
                  <Button variant="secondary" size="sm">
                    <Download size={14} /> Export
                    <ChevronDown size={12} />
                  </Button>
                </Popover.Trigger>
                <Popover.Portal>
                  <Popover.Content
                    align="end"
                    sideOffset={4}
                    className="w-48 bg-bg-surface border border-border rounded-lg shadow-xl z-[50] animate-fade-in"
                  >
                    <a
                      href={`/api/v1/episodes/${episodeId}/export/video`}
                      className="flex items-center gap-2 px-3 py-2.5 text-sm text-txt-primary hover:bg-bg-hover rounded-t-lg"
                    >
                      <Film size={14} /> Video (.mp4)
                    </a>
                    <a
                      href={`/api/v1/episodes/${episodeId}/export/thumbnail`}
                      className="flex items-center gap-2 px-3 py-2.5 text-sm text-txt-primary hover:bg-bg-hover"
                    >
                      <ImageIcon size={14} /> Thumbnail (.jpg)
                    </a>
                    <Popover.Close asChild>
                      <button
                        onClick={() => setThumbEditorOpen(true)}
                        className="flex items-center gap-2 w-full text-left px-3 py-2.5 text-sm text-txt-primary hover:bg-bg-hover"
                      >
                        <ImageIcon size={14} /> Edit thumbnail…
                      </button>
                    </Popover.Close>
                    <a
                      href={`/api/v1/episodes/${episodeId}/export/description`}
                      className="flex items-center gap-2 px-3 py-2.5 text-sm text-txt-primary hover:bg-bg-hover"
                    >
                      <FileText size={14} /> Description (.txt)
                    </a>
                    <a
                      href={`/api/v1/episodes/${episodeId}/export/bundle`}
                      className="flex items-center gap-2 px-3 py-2.5 text-sm text-txt-primary hover:bg-bg-hover border-t border-border"
                    >
                      <Archive size={14} /> Download All (.zip)
                    </a>
                    <a
                      href={`/api/v1/episodes/${episodeId}/export/raw-assets`}
                      className="flex items-center gap-2 px-3 py-2.5 text-sm text-txt-primary hover:bg-bg-hover border-t border-border"
                      title="Per-scene images, voice segments, captions"
                    >
                      <Archive size={14} /> Raw assets (.zip)
                    </a>
                    {youtubeConnected && (
                      <Popover.Close asChild>
                        <button
                          onClick={() => setUploadDialogOpen(true)}
                          className="flex items-center gap-2 w-full text-left px-3 py-2.5 text-sm text-error hover:bg-bg-hover border-t border-border"
                        >
                          <Upload size={14} /> Upload to YouTube
                        </button>
                      </Popover.Close>
                    )}
                    <Popover.Close asChild>
                      <button
                        onClick={() => setPublishAllOpen(true)}
                        className="flex items-center gap-2 w-full text-left px-3 py-2.5 text-sm text-accent hover:bg-bg-hover border-t border-border rounded-b-lg"
                      >
                        <Upload size={14} /> Publish everywhere…
                      </button>
                    </Popover.Close>
                  </Popover.Content>
                </Popover.Portal>
              </Popover.Root>
            </div>
          )}

          {/* Publish action row */}
          <PublishRow
            status={episode.status}
            action={action.kind}
            youtubeConnected={youtubeConnected}
            episodeId={episodeId!}
            onOpenSchedule={openScheduleDialog}
            onOpenUpload={() => setUploadDialogOpen(true)}
            onOpenPublishAll={() => setPublishAllOpen(true)}
            onOpenSeo={() => void handleSeo()}
            onOpenThumbEditor={() => setThumbEditorOpen(true)}
          />

          {/* Tab strip — horizontally scrollable on mobile */}
          <div className="flex overflow-x-auto scrollbar-hidden border-b border-border -mb-px snap-x snap-mandatory">
            {TABS.map((tab) => {
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={[
                    'flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium transition-colors duration-fast',
                    'border-b-2 whitespace-nowrap snap-start',
                    'min-h-[44px] md:min-h-0',
                    isActive
                      ? 'border-accent text-accent'
                      : 'border-transparent text-txt-tertiary hover:text-txt-secondary',
                  ].join(' ')}
                >
                  <tab.icon size={14} />
                  {tab.label}
                </button>
              );
            })}
          </div>

          {/* Tab content */}
          <div className="min-h-[400px]">
            <Suspense
              fallback={
                <div className="flex items-center justify-center h-40">
                  <Spinner />
                </div>
              }
            >
              {activeTab === 'script' && (
                <ScriptTab
                  episode={episode}
                  scenes={scenes}
                  onRefresh={fetchEpisode}
                  episodeId={episodeId!}
                  voiceProfiles={voiceProfiles}
                  epVoiceId={epVoiceId}
                  setEpVoiceId={setEpVoiceId}
                />
              )}
              {activeTab === 'scenes' && (
                <ScenesTab
                  episode={episode}
                  scenes={scenes}
                  onRefresh={fetchEpisode}
                />
              )}
              {activeTab === 'captions' && (
                <CaptionsTab
                  episode={episode}
                  captionsAsset={captionsAsset}
                  onRefresh={fetchEpisode}
                  episodeId={episodeId!}
                  epCaptionStyle={epCaptionStyle}
                  setEpCaptionStyle={setEpCaptionStyle}
                />
              )}
              {activeTab === 'music' && (
                <MusicTab
                  episodeId={episodeId!}
                  episode={episode}
                  onChanged={() => void fetchEpisode()}
                />
              )}
              {activeTab === 'metadata' && (
                <MetadataTab episode={episode} />
              )}
            </Suspense>
          </div>
        </main>
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* Dialogs — unchanged from original                                  */}
      {/* ------------------------------------------------------------------ */}

      {/* Cancel confirmation */}
      <Dialog
        open={cancelDialogOpen}
        onClose={() => setCancelDialogOpen(false)}
        title="Cancel Generation?"
      >
        <p className="text-sm text-txt-secondary">
          This will stop the current generation pipeline for this episode. Any
          completed steps will be preserved, but in-progress work will be lost.
        </p>
        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => setCancelDialogOpen(false)}
          >
            Keep Running
          </Button>
          <Button
            variant="destructive"
            loading={action.kind === 'cancelling'}
            onClick={() => void handleCancel()}
          >
            Cancel Generation
          </Button>
        </DialogFooter>
      </Dialog>

      {/* Delete confirmation */}
      <Dialog
        open={deleteDialogOpen}
        onClose={() => setDeleteDialogOpen(false)}
        title="Delete Episode?"
      >
        <p className="text-sm text-txt-secondary">
          This will permanently delete the episode and all generated media. This
          action cannot be undone.
        </p>
        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => setDeleteDialogOpen(false)}
          >
            Cancel
          </Button>
          <Button
            variant="destructive"
            loading={action.kind === 'deleting'}
            onClick={() => void handleDelete()}
          >
            <Trash2 size={14} />
            Delete Forever
          </Button>
        </DialogFooter>
      </Dialog>

      {/* Schedule */}
      <Dialog
        open={scheduleDialogOpen}
        onClose={() => setScheduleDialogOpen(false)}
        title="Schedule Post"
      >
        <div className="space-y-4">
          <Select
            label="Platform"
            value={schedPlatform}
            onChange={(e) => setSchedPlatform(e.target.value)}
            options={[
              { value: 'youtube', label: 'YouTube' },
              { value: 'tiktok', label: 'TikTok' },
              { value: 'instagram', label: 'Instagram' },
              { value: 'x', label: 'X (Twitter)' },
            ]}
          />
          <Input
            label="Scheduled date & time"
            type="datetime-local"
            value={schedDatetime}
            onChange={(e) => setSchedDatetime(e.target.value)}
          />
          <Input
            label="Title"
            value={schedTitle}
            onChange={(e) => setSchedTitle(e.target.value)}
            placeholder="Post title"
          />
          <Select
            label="Privacy"
            value={schedPrivacy}
            onChange={(e) => setSchedPrivacy(e.target.value)}
            options={[
              { value: 'private', label: 'Private' },
              { value: 'unlisted', label: 'Unlisted' },
              { value: 'public', label: 'Public' },
            ]}
          />
        </div>
        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => setScheduleDialogOpen(false)}
          >
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={action.kind === 'scheduling'}
            onClick={async () => {
              if (!episodeId) return;
              setAction({ kind: 'scheduling' });
              try {
                await scheduleApi.create({
                  content_type: 'episode',
                  content_id: episodeId,
                  platform: schedPlatform,
                  scheduled_at: new Date(schedDatetime).toISOString(),
                  title: schedTitle,
                  privacy: schedPrivacy,
                });
                setScheduleDialogOpen(false);
                toast.success('Post scheduled');
              } catch (err) {
                toast.error('Failed to schedule post', {
                  description: String(err),
                });
              } finally {
                setAction({ kind: 'idle' });
              }
            }}
          >
            Schedule
          </Button>
        </DialogFooter>
      </Dialog>

      {/* YouTube Upload */}
      <Dialog
        open={uploadDialogOpen}
        onClose={() => setUploadDialogOpen(false)}
        title="Upload to YouTube"
      >
        <div className="space-y-4">
          <Input
            label="Title"
            value={ytTitle}
            onChange={(e) => setYtTitle(e.target.value)}
            placeholder="Video title for YouTube"
          />
          <Textarea
            label="Description"
            value={ytDescription}
            onChange={(e) => setYtDescription(e.target.value)}
            className="min-h-[100px]"
            placeholder="Video description..."
          />
          <Input
            label="Tags (comma-separated)"
            value={ytTags}
            onChange={(e) => setYtTags(e.target.value)}
            placeholder="shorts, tutorial, medieval"
          />
          <Select
            label="Privacy"
            value={ytPrivacy}
            onChange={(e) => setYtPrivacy(e.target.value)}
            options={[
              { value: 'private', label: 'Private' },
              { value: 'unlisted', label: 'Unlisted' },
              { value: 'public', label: 'Public' },
            ]}
          />
        </div>
        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => setUploadDialogOpen(false)}
          >
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={action.kind === 'uploading'}
            onClick={() => void handleYouTubeUpload()}
          >
            <Upload size={14} /> Upload
          </Button>
        </DialogFooter>
      </Dialog>

      {/* Publish everywhere */}
      <Dialog
        open={publishAllOpen}
        onClose={() => setPublishAllOpen(false)}
        title="Publish everywhere"
        description="Fan out this episode to every platform you have connected. Platforms without a connected account will be skipped with a clear reason."
      >
        <div className="space-y-3 text-sm">
          {(['youtube', 'tiktok', 'instagram'] as const).map((p) => (
            <label
              key={p}
              className="flex items-center gap-3 rounded-md border border-border p-3 cursor-pointer hover:bg-bg-hover"
            >
              <input
                type="checkbox"
                checked={publishAllPlatforms[p]}
                onChange={(e) =>
                  setPublishAllPlatforms((prev) => ({
                    ...prev,
                    [p]: e.target.checked,
                  }))
                }
                className="accent-accent"
              />
              <span className="flex-1 text-txt-primary">
                {p === 'youtube'
                  ? 'YouTube'
                  : p === 'tiktok'
                    ? 'TikTok'
                    : 'Instagram'}
              </span>
              {p === 'youtube' && (
                <span className="text-[11px] text-txt-muted">all tiers</span>
              )}
              {(p === 'tiktok' || p === 'instagram') && (
                <span className="text-[11px] text-amber-300">
                  Studio tier
                </span>
              )}
            </label>
          ))}
          <p className="text-[11px] text-txt-muted">
            Uses the episode's SEO title + description when available. Uploads
            go to the Activity Monitor — you can cancel individual uploads from
            there.
          </p>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setPublishAllOpen(false)}>
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={action.kind === 'publishingAll'}
            disabled={!Object.values(publishAllPlatforms).some(Boolean)}
            onClick={async () => {
              const platforms = (
                Object.entries(publishAllPlatforms) as [
                  'youtube' | 'tiktok' | 'instagram',
                  boolean,
                ][]
              )
                .filter(([, v]) => v)
                .map(([k]) => k);
              setAction({ kind: 'publishingAll' });
              try {
                const result = await episodesApi.publishAll(episodeId!, {
                  platforms,
                });
                const accepted = result.accepted.map((a) => a.platform);
                const skipped = result.skipped;
                if (accepted.length > 0) {
                  toast.success(`Publishing to ${accepted.join(', ')}`, {
                    description: skipped.length
                      ? `Skipped: ${skipped.map((s) => `${s.platform} (${s.reason})`).join('; ')}`
                      : 'Watch progress in the Activity Monitor.',
                  });
                } else if (skipped.length > 0) {
                  toast.error('Nothing to publish', {
                    description: skipped
                      .map((s) => `${s.platform}: ${s.reason}`)
                      .join('; '),
                  });
                }
                setPublishAllOpen(false);
              } catch (err) {
                toast.error('Publish-all failed', {
                  description: String(err),
                });
              } finally {
                setAction({ kind: 'idle' });
              }
            }}
          >
            Publish
          </Button>
        </DialogFooter>
      </Dialog>

      {/* Thumbnail editor */}
      <ThumbnailEditor
        open={thumbEditorOpen}
        onClose={() => setThumbEditorOpen(false)}
        episodeId={episodeId ?? ''}
        currentThumbnailUrl={
          episode?.metadata_?.thumbnail_path
            ? `/storage/${episode.metadata_.thumbnail_path}`
            : null
        }
        onSaved={() => void fetchEpisode()}
      />

      {/* SEO Optimisation Dialog */}
      <Dialog
        open={seoOpen}
        onClose={() => setSeoOpen(false)}
        title="SEO Optimisation"
      >
        {action.kind === 'generatingSeo' ? (
          <div className="flex items-center justify-center py-10 gap-3">
            <Loader2 size={20} className="animate-spin text-accent" />
            <p className="text-sm text-txt-secondary">
              Generating SEO content — this may take up to 30 seconds...
            </p>
          </div>
        ) : seoData ? (
          <div className="space-y-4">
            {seoData.virality_score !== undefined && (
              <div className="flex items-center gap-2 p-3 bg-bg-elevated rounded-lg border border-border">
                <span className="text-xs font-semibold text-txt-secondary uppercase tracking-wide">
                  Virality Score
                </span>
                <span
                  className={[
                    'ml-auto text-lg font-bold',
                    seoData.virality_score >= 75
                      ? 'text-success'
                      : seoData.virality_score >= 50
                        ? 'text-warning'
                        : 'text-txt-secondary',
                  ].join(' ')}
                >
                  {seoData.virality_score}
                  <span className="text-xs font-normal text-txt-tertiary">
                    {' '}
                    / 100
                  </span>
                </span>
              </div>
            )}
            <div>
              <label className="text-xs font-semibold text-txt-secondary">
                Optimised Title
              </label>
              <p className="text-sm text-txt-primary mt-1 bg-bg-elevated p-2 rounded">
                {seoData.title}
              </p>
            </div>
            <div>
              <label className="text-xs font-semibold text-txt-secondary">
                Hook Line
              </label>
              <p className="text-sm text-accent mt-1 italic bg-bg-elevated p-2 rounded">
                &quot;{seoData.hook}&quot;
              </p>
            </div>
            <div>
              <label className="text-xs font-semibold text-txt-secondary">
                Description
              </label>
              <p className="text-xs text-txt-secondary mt-1 bg-bg-elevated p-2 rounded whitespace-pre-wrap">
                {seoData.description}
              </p>
            </div>
            <div>
              <label className="text-xs font-semibold text-txt-secondary">
                Hashtags
              </label>
              <div className="flex flex-wrap gap-1 mt-1">
                {(seoData.hashtags || []).map((h, i) => (
                  <Badge key={i} variant="neutral" className="text-xs">
                    {h}
                  </Badge>
                ))}
              </div>
            </div>
            <div>
              <label className="text-xs font-semibold text-txt-secondary">
                Tags
              </label>
              <div className="flex flex-wrap gap-1 mt-1">
                {(seoData.tags || []).map((t, i) => (
                  <span
                    key={i}
                    className="text-xs text-txt-tertiary bg-bg-hover px-2 py-0.5 rounded"
                  >
                    {t}
                  </span>
                ))}
              </div>
            </div>
          </div>
        ) : null}
        <DialogFooter>
          <Button variant="ghost" onClick={() => setSeoOpen(false)}>
            Close
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}

export default EpisodeDetail;
