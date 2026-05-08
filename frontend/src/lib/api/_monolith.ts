// =============================================================================
// Drevalis Creator Studio API Client
// Typed fetch wrapper for all backend CRUD operations.
// =============================================================================

import type {
  Series,
  SeriesCreate,
  SeriesUpdate,
  SeriesListItem,
  SeriesGenerateResponse,
  Episode,
  EpisodeCreate,
  EpisodeUpdate,
  EpisodeListItem,
  GenerateRequest,
  GenerateResponse,
  RetryResponse,
  ScriptUpdate,
  VoiceProfile,
  VoiceProfileCreate,
  VoiceProfileUpdate,
  VoiceTestResponse,
  ComfyUIServer,
  ComfyUIServerCreate,
  ComfyUIServerUpdate,
  ComfyUIServerTestResponse,
  ComfyUIWorkflow,
  ComfyUIWorkflowCreate,
  ComfyUIWorkflowUpdate,
  LLMConfig,
  LLMConfigCreate,
  LLMConfigUpdate,
  LLMTestResponse,
  PromptTemplate,
  PromptTemplateCreate,
  PromptTemplateUpdate,
  GenerationJob,
  GenerationJobExtended,
  GenerationJobListItem,
  StorageUsage,
  HealthCheck,
  FFmpegInfo,
  Audiobook,
  AudiobookCreate,
  YouTubeChannel,
  YouTubeUpload,
  YouTubeUploadRequest,
  YouTubePlaylist,
  YouTubeVideoStats,
  CharacterPack,
  CharacterPackCreate,
} from '@/types';
import type { components } from '@/types/api';

// Shorthand for ``components['schemas'][K]`` — call sites that adopt
// generated types should use this instead of the verbose lookup.
// The hand-rolled types in ``@/types`` stay around; migration is
// opt-in per call site.
type ApiSchema = components['schemas'];

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '';

// ---------------------------------------------------------------------------
// Error class
// ---------------------------------------------------------------------------

// AudiobookClip — emitted by GET /audiobooks/{id}/clips, consumed
// by the AudiobookEditor timeline (v0.25.0).
export interface AudiobookClip {
  id: string;
  kind: 'voice_single' | 'voice_multi' | 'sfx' | 'music';
  chapter: number;
  filename: string;
  duration_seconds: number;
  url: string;
  label: string;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public statusText: string,
    public detail?: string,
    public detailRaw?: unknown,
  ) {
    super(detail ?? `${status} ${statusText}`);
    this.name = 'ApiError';
  }

  /** Safe string representation — never returns `[object Object]`. */
  override toString(): string {
    return `${this.name} (${this.status}): ${this.message}`;
  }
}

/**
 * Extract a human-readable message from any caught value.
 *
 * Fixes the `[object Object]` bug where `String(err)` on a custom
 * Error with a non-string payload produces `[object Object]`.
 */
export function formatError(err: unknown): string {
  if (err instanceof ApiError) {
    return err.toString();
  }
  if (err instanceof Error) {
    return err.message || err.toString();
  }
  if (typeof err === 'string') return err;
  try {
    return JSON.stringify(err);
  } catch {
    return String(err);
  }
}

// ---------------------------------------------------------------------------
// Core fetch helpers
// ---------------------------------------------------------------------------

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const url = `${BASE_URL}${path}`;
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...((options.headers as Record<string, string>) ?? {}),
  };

  const response = await fetch(url, {
    credentials: 'same-origin',
    ...options,
    headers,
  });

  if (!response.ok) {
    let detail: string | undefined;
    let detailRaw: unknown;
    try {
      const body = await response.json();
      const rawDetail = body?.detail;
      detailRaw = rawDetail ?? body;
      if (typeof rawDetail === 'string') {
        detail = rawDetail;
      } else if (rawDetail && typeof rawDetail === 'object') {
        detail = JSON.stringify(rawDetail);
      } else {
        detail = JSON.stringify(body);
      }
    } catch {
      detail = response.statusText;
    }
    if (response.status === 402 && typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('license-gate-triggered', { detail }));
    }
    throw new ApiError(response.status, response.statusText, detail, detailRaw);
  }

  // 204 No Content
  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

function get<T>(path: string): Promise<T> {
  return request<T>(path, { method: 'GET' });
}

function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

function put<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: 'PUT',
    body: JSON.stringify(body),
  });
}

function del<T = void>(path: string): Promise<T> {
  return request<T>(path, { method: 'DELETE' });
}

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------

export const health = {
  check: () => get<{ status: string; version: string }>('/api/v1/health'),
};

// ---------------------------------------------------------------------------
// Series
// ---------------------------------------------------------------------------

export const series = {
  list: () => get<SeriesListItem[]>('/api/v1/series'),

  get: (id: string) => get<Series>(`/api/v1/series/${id}`),

  create: (data: SeriesCreate) => post<Series>('/api/v1/series', data),

  update: (id: string, data: SeriesUpdate) =>
    put<Series>(`/api/v1/series/${id}`, data),

  delete: (id: string) => del(`/api/v1/series/${id}`),

  generate: (data: {
    idea: string;
    episode_count?: number;
    target_duration_seconds?: number;
    voice_profile_id?: string;
    llm_config_id?: string;
  }) =>
    post<{ job_id: string; status: string }>('/api/v1/series/generate', data),

  getGenerateJob: (jobId: string) =>
    get<{
      job_id: string;
      status: string;
      result: SeriesGenerateResponse | null;
      error: string | null;
    }>(`/api/v1/series/generate-job/${jobId}`),

  addEpisodesAi: (seriesId: string, count: number = 5) =>
    post<{ message: string; episode_ids: string[]; episodes: Array<{ title: string; topic: string }> }>(
      `/api/v1/series/${seriesId}/add-episodes`,
      { count },
    ),

  trendingTopics: (seriesId: string) =>
    post<{ series_id: string; topics: Array<{ title: string; angle?: string; hook?: string; estimated_engagement?: string }> }>(
      `/api/v1/series/${seriesId}/trending-topics`,
    ),
};

// ---------------------------------------------------------------------------
// Episodes
// ---------------------------------------------------------------------------

export const episodes = {
  list: (params?: { series_id?: string; status?: string; limit?: number }) => {
    const query = new URLSearchParams();
    if (params?.series_id) query.set('series_id', params.series_id);
    if (params?.status) query.set('status', params.status);
    query.set('limit', String(params?.limit ?? 500));
    const qs = query.toString();
    return get<EpisodeListItem[]>(`/api/v1/episodes${qs ? `?${qs}` : ''}`);
  },

  recent: (limit = 10) =>
    get<EpisodeListItem[]>(`/api/v1/episodes/recent?limit=${limit}`),

  get: (id: string) => get<Episode>(`/api/v1/episodes/${id}`),

  create: (data: EpisodeCreate) => post<Episode>('/api/v1/episodes', data),

  update: (id: string, data: EpisodeUpdate) =>
    put<Episode>(`/api/v1/episodes/${id}`, data),

  delete: (id: string) => del(`/api/v1/episodes/${id}`),

  generate: (id: string, data?: GenerateRequest) =>
    post<GenerateResponse>(`/api/v1/episodes/${id}/generate`, data ?? {}),

  retry: (id: string) =>
    post<RetryResponse>(`/api/v1/episodes/${id}/retry`),

  seoPreflight: (id: string) =>
    post<{
      score: number;
      grade: string;
      blocking: boolean;
      checks: Array<{
        id: string;
        severity: 'pass' | 'warn' | 'fail' | 'info';
        title: string;
        message: string;
        suggestion: string | null;
      }>;
    }>(`/api/v1/episodes/${id}/seo-preflight`),

  seoVariants: (id: string) =>
    post<{
      titles: string[];
      thumbnail_prompts: string[];
      descriptions: string[];
    }>(`/api/v1/episodes/${id}/seo-variants`),

  continuity: (id: string) =>
    post<{
      issues: Array<{
        from_scene: number;
        to_scene: number;
        severity: 'info' | 'warn' | 'fail';
        issue: string;
        suggestion: string;
      }>;
    }>(`/api/v1/episodes/${id}/continuity`),

  retryStep: (id: string, step: string) =>
    post<RetryResponse>(`/api/v1/episodes/${id}/retry/${step}`),

  getScript: (id: string) =>
    get<Record<string, unknown> | null>(`/api/v1/episodes/${id}/script`),

  updateScript: (id: string, data: ScriptUpdate) =>
    put<Record<string, unknown>>(`/api/v1/episodes/${id}/script`, data),

  // ── Scene-level operations ──────────────────────────────────────────

  updateScene: (
    episodeId: string,
    sceneNumber: number,
    data: {
      narration?: string;
      visual_prompt?: string;
      duration_seconds?: number;
      keywords?: string[];
    },
  ) =>
    put<{ message: string; scene: Record<string, unknown> }>(
      `/api/v1/episodes/${episodeId}/scenes/${sceneNumber}`,
      data,
    ),

  deleteScene: (episodeId: string, sceneNumber: number) =>
    del<{ message: string; remaining_scenes: number; media_assets_deleted: number }>(
      `/api/v1/episodes/${episodeId}/scenes/${sceneNumber}`,
    ),

  // ── Regeneration endpoints ──────────────────────────────────────────

  regenerateScene: (
    episodeId: string,
    sceneNumber: number,
    prompt?: string,
  ) =>
    post<{ message: string; episode_id: string; scene_number: number; job_ids: string[] }>(
      `/api/v1/episodes/${episodeId}/regenerate-scene/${sceneNumber}`,
      prompt ? { visual_prompt: prompt } : undefined,
    ),

  regenerateVoice: (episodeId: string, voiceProfileId?: string) =>
    post<{ message: string; episode_id: string; job_ids: string[] }>(
      `/api/v1/episodes/${episodeId}/regenerate-voice`,
      voiceProfileId ? { voice_profile_id: voiceProfileId } : undefined,
    ),

  reassemble: (episodeId: string) =>
    post<{ message: string; episode_id: string; job_ids: string[] }>(
      `/api/v1/episodes/${episodeId}/reassemble`,
    ),

  seoScore: (episodeId: string) =>
    get<SEOScore>(`/api/v1/episodes/${episodeId}/seo-score`),

  publishAll: (
    episodeId: string,
    data: {
      platforms: ('youtube' | 'tiktok' | 'instagram')[];
      title?: string;
      description?: string;
      privacy?: 'public' | 'unlisted' | 'private';
    },
  ) =>
    post<{
      episode_id: string;
      accepted: { platform: string; upload_id: string }[];
      skipped: { platform: string; reason: string }[];
    }>(`/api/v1/episodes/${episodeId}/publish-all`, data),

  regenerateCaptions: (episodeId: string, captionStyle: string) =>
    post<{ message: string; episode_id: string; job_ids: string[] }>(
      `/api/v1/episodes/${episodeId}/regenerate-captions?caption_style=${encodeURIComponent(captionStyle)}`,
      {},
    ),

  setMusic: (
    episodeId: string,
    data: {
      music_enabled: boolean;
      music_mood?: string;
      music_volume_db?: number;
      reassemble?: boolean;
    },
  ) =>
    post<{ message: string; episode_id: string }>(
      `/api/v1/episodes/${episodeId}/set-music`,
      data,
    ),

  bulkGenerate: (episodeIds: string[]) =>
    post<{ queued: number; skipped: number }>(
      '/api/v1/episodes/bulk-generate',
      { episode_ids: episodeIds },
    ),

  // ── Episode management ──────────────────────────────────────────────

  duplicate: (episodeId: string) =>
    post<Episode>(`/api/v1/episodes/${episodeId}/duplicate`),

  resetToDraft: (episodeId: string) =>
    post<{ message: string; episode_id: string; jobs_deleted: number }>(
      `/api/v1/episodes/${episodeId}/reset`,
    ),

  cancel: (episodeId: string) =>
    post<{ message: string; episode_id: string; cancelled_jobs: number }>(
      `/api/v1/episodes/${episodeId}/cancel`,
      {},
    ),

  // ── Music ──────────────────────────────────────────────────────────

  musicList: (episodeId: string) =>
    get<Array<{ filename: string; path: string; mood: string; duration: number }>>(
      `/api/v1/episodes/${episodeId}/music`,
    ),

  musicGenerate: (episodeId: string, mood: string, duration: number = 30) =>
    post<{ message: string; path: string; duration: number }>(
      `/api/v1/episodes/${episodeId}/music/generate`,
      { mood, duration },
    ),

  musicSelect: (episodeId: string, musicPath: string) =>
    post<{ message: string }>(
      `/api/v1/episodes/${episodeId}/music/select`,
      { music_path: musicPath },
    ),

  generateSeo: (episodeId: string) =>
    post<{ title: string; description: string; hashtags: string[]; tags: string[]; hook: string; virality_score?: number }>(
      `/api/v1/episodes/${episodeId}/seo`,
    ),
};

// ---------------------------------------------------------------------------
// Voice Profiles
// ---------------------------------------------------------------------------

export const voiceProfiles = {
  list: (params?: { provider?: string; language_code?: string }) => {
    const qs = new URLSearchParams();
    if (params?.provider) qs.set('provider', params.provider);
    if (params?.language_code) qs.set('language_code', params.language_code);
    const q = qs.toString();
    return get<VoiceProfile[]>(`/api/v1/voice-profiles${q ? `?${q}` : ''}`);
  },

  get: (id: string) => get<VoiceProfile>(`/api/v1/voice-profiles/${id}`),

  create: (data: VoiceProfileCreate) =>
    post<VoiceProfile>('/api/v1/voice-profiles', data),

  update: (id: string, data: VoiceProfileUpdate) =>
    put<VoiceProfile>(`/api/v1/voice-profiles/${id}`, data),

  delete: (id: string) => del(`/api/v1/voice-profiles/${id}`),

  test: (id: string, text?: string) =>
    post<VoiceTestResponse>(`/api/v1/voice-profiles/${id}/test`, text ? { text } : undefined),

  clone: (data: {
    asset_id: string;
    display_name: string;
    provider?: 'elevenlabs' | 'piper' | 'kokoro';
    language_code?: string;
  }) =>
    post<{
      voice_profile_id: string;
      provider: string;
      status: string;
      note: string;
    }>('/api/v1/voice-profiles/clone', data),
};

// ---------------------------------------------------------------------------
// ComfyUI Servers
// ---------------------------------------------------------------------------

export const comfyuiServers = {
  list: () => get<ComfyUIServer[]>('/api/v1/comfyui/servers'),

  get: (id: string) => get<ComfyUIServer>(`/api/v1/comfyui/servers/${id}`),

  create: (data: ComfyUIServerCreate) =>
    post<ComfyUIServer>('/api/v1/comfyui/servers', data),

  update: (id: string, data: ComfyUIServerUpdate) =>
    put<ComfyUIServer>(`/api/v1/comfyui/servers/${id}`, data),

  delete: (id: string) => del(`/api/v1/comfyui/servers/${id}`),

  test: (id: string) =>
    post<ComfyUIServerTestResponse>(`/api/v1/comfyui/servers/${id}/test`),
};

// ---------------------------------------------------------------------------
// ComfyUI Workflows
// ---------------------------------------------------------------------------

export const comfyuiWorkflows = {
  list: () => get<ComfyUIWorkflow[]>('/api/v1/comfyui/workflows'),

  get: (id: string) =>
    get<ComfyUIWorkflow>(`/api/v1/comfyui/workflows/${id}`),

  create: (data: ComfyUIWorkflowCreate) =>
    post<ComfyUIWorkflow>('/api/v1/comfyui/workflows', data),

  update: (id: string, data: ComfyUIWorkflowUpdate) =>
    put<ComfyUIWorkflow>(`/api/v1/comfyui/workflows/${id}`, data),

  delete: (id: string) => del(`/api/v1/comfyui/workflows/${id}`),
};

// ---------------------------------------------------------------------------
// LLM Configs
// ---------------------------------------------------------------------------

export const llmConfigs = {
  list: () => get<LLMConfig[]>('/api/v1/llm'),

  get: (id: string) => get<LLMConfig>(`/api/v1/llm/${id}`),

  create: (data: LLMConfigCreate) => post<LLMConfig>('/api/v1/llm', data),

  update: (id: string, data: LLMConfigUpdate) =>
    put<LLMConfig>(`/api/v1/llm/${id}`, data),

  delete: (id: string) => del(`/api/v1/llm/${id}`),

  test: (id: string, prompt?: string) =>
    post<LLMTestResponse>(`/api/v1/llm/${id}/test`, prompt ? { prompt } : undefined),
};

// ---------------------------------------------------------------------------
// Prompt Templates
// ---------------------------------------------------------------------------

export const promptTemplates = {
  list: (templateType?: string) => {
    const qs = templateType ? `?template_type=${templateType}` : '';
    return get<PromptTemplate[]>(`/api/v1/prompt-templates${qs}`);
  },

  get: (id: string) =>
    get<PromptTemplate>(`/api/v1/prompt-templates/${id}`),

  create: (data: PromptTemplateCreate) =>
    post<PromptTemplate>('/api/v1/prompt-templates', data),

  update: (id: string, data: PromptTemplateUpdate) =>
    put<PromptTemplate>(`/api/v1/prompt-templates/${id}`, data),

  delete: (id: string) => del(`/api/v1/prompt-templates/${id}`),
};

// ---------------------------------------------------------------------------
// Generation Jobs
// ---------------------------------------------------------------------------

export const jobs = {
  list: (params?: { episode_id?: string; status?: string }) => {
    const query = new URLSearchParams();
    if (params?.episode_id) query.set('episode_id', params.episode_id);
    if (params?.status) query.set('status', params.status);
    const qs = query.toString();
    return get<GenerationJobListItem[]>(`/api/v1/jobs${qs ? `?${qs}` : ''}`);
  },

  all: (params?: {
    status?: string;
    episode_id?: string;
    step?: string;
    limit?: number;
    offset?: number;
  }) => {
    const query = new URLSearchParams();
    if (params?.status) query.set('status', params.status);
    if (params?.episode_id) query.set('episode_id', params.episode_id);
    if (params?.step) query.set('step', params.step);
    if (params?.limit) query.set('limit', String(params.limit));
    if (params?.offset) query.set('offset', String(params.offset));
    const qs = query.toString();
    return get<GenerationJobExtended[]>(`/api/v1/jobs/all${qs ? `?${qs}` : ''}`);
  },

  active: () => get<GenerationJobListItem[]>('/api/v1/jobs/active'),

  get: (id: string) => get<GenerationJob>(`/api/v1/jobs/${id}`),

  status: () =>
    get<{
      active: number;
      queued: number;
      max_concurrent: number;
      slots_available: number;
      generating_episodes: number;
      total_generating_episodes: number;
      total_failed_episodes: number;
    }>('/api/v1/jobs/status'),

  cancelAll: () =>
    post<{ message: string; cancelled_episodes: number; cancelled_jobs: number }>(
      '/api/v1/jobs/cancel-all',
      {},
    ),

  retryAllFailed: (priority?: 'shorts_first' | 'longform_first' | 'fifo') =>
    post<{ message: string; retried: number; total_failed: number; priority: string }>(
      `/api/v1/jobs/retry-all-failed${priority ? `?priority=${priority}` : ''}`,
      {},
    ),

  pauseAll: () =>
    post<{ message: string; paused: number }>(
      '/api/v1/jobs/pause-all',
      {},
    ),

  cleanup: () =>
    post<{ message: string; cleaned_jobs: number; reset_episodes: number }>(
      '/api/v1/jobs/cleanup',
      {},
    ),

  setPriority: (mode: 'shorts_first' | 'longform_first' | 'fifo') =>
    post<{ message: string; mode: string }>(`/api/v1/jobs/set-priority?mode=${mode}`, {}),

  getPriority: () =>
    get<{ mode: string }>('/api/v1/jobs/priority'),

  cancelJob: (jobId: string) =>
    post<{ message: string; job_id: string; episode_id: string; episode_cancelled: boolean }>(
      `/api/v1/jobs/${jobId}/cancel`,
      {},
    ),

  tasksActive: () =>
    get<{
      tasks: Array<{
        type: 'episode_generation' | 'audiobook_generation' | 'script_generation';
        id: string;
        title: string;
        step: string;
        status: string;
        progress: number;
        url: string;
      }>;
    }>('/api/v1/jobs/tasks/active'),

  workerHealth: () =>
    get<{ alive: boolean; last_heartbeat: string | null; generating_count: number }>(
      '/api/v1/jobs/worker/health',
    ),

  restartWorker: () =>
    post<{ message: string }>('/api/v1/jobs/worker/restart', {}),
};

// ---------------------------------------------------------------------------
// Audiobooks
// ---------------------------------------------------------------------------

export const audiobooks = {
  list: () => get<Audiobook[]>('/api/v1/audiobooks'),

  get: (id: string) => get<Audiobook>(`/api/v1/audiobooks/${id}`),

  create: (data: AudiobookCreate) =>
    post<Audiobook>('/api/v1/audiobooks', data),

  delete: (id: string) => del(`/api/v1/audiobooks/${id}`),

  updateText: (id: string, text: string) =>
    put<Audiobook>(`/api/v1/audiobooks/${id}/text`, { text }),

  regenerateChapter: (id: string, chapterIndex: number, newText?: string) =>
    post<{ message: string; audiobook_id: string; chapter_index: number }>(
      `/api/v1/audiobooks/${id}/regenerate-chapter/${chapterIndex}`,
      newText ? { text: newText } : {},
    ),

  regenerateChapterImage: (
    id: string,
    chapterIndex: number,
    promptOverride?: string,
  ) =>
    post<{ message: string; audiobook_id: string; chapter_index: number }>(
      `/api/v1/audiobooks/${id}/regenerate-chapter-image/${chapterIndex}`,
      promptOverride ? { prompt_override: promptOverride } : {},
    ),

  regenerate: (id: string) =>
    post<{ message: string; audiobook_id: string }>(
      `/api/v1/audiobooks/${id}/regenerate`,
    ),

  updateVoices: (id: string, data: { voice_casting: Record<string, string>; voice_profile_id?: string; regenerate: boolean }) =>
    put<{ message: string }>(`/api/v1/audiobooks/${id}/voices`, data),

  generateScript: (data: {
    concept: string;
    characters: Array<{ name: string; description: string }>;
    target_minutes: number;
    mood: string;
  }) =>
    post<{ job_id: string; status: string }>('/api/v1/audiobooks/generate-script', data),

  getScriptJob: (jobId: string) =>
    get<{
      job_id: string;
      status: string;
      result: {
        title: string;
        script: string;
        characters: string[];
        chapters: string[];
        word_count: number;
        estimated_minutes: number;
      } | null;
      error: string | null;
    }>(`/api/v1/audiobooks/script-job/${jobId}`),

  cancelScriptJob: (jobId: string) =>
    post<{ message: string }>(`/api/v1/audiobooks/script-job/${jobId}/cancel`, {}),

  // Cancel an in-progress audiobook generation. Sets a Redis flag
  // the worker polls between major steps; the actual stop lands at
  // the next boundary.
  cancel: (audiobookId: string) =>
    post<{ message: string; audiobook_id: string }>(
      `/api/v1/audiobooks/${audiobookId}/cancel`,
      {},
    ),

  // Render a short music preview so the user can hear the mood +
  // ducking behaviour before committing to a full generation run.
  musicPreview: (
    audiobookId: string,
    mood: string,
    seconds = 30,
    volumeDb = -14,
  ) =>
    post<{ audiobook_id: string; mood: string; seconds: number; url: string; rel_path: string }>(
      `/api/v1/audiobooks/${audiobookId}/music-preview?mood=${encodeURIComponent(mood)}&seconds=${seconds}&volume_db=${volumeDb}`,
      {},
    ),

  // Re-render the audio mix with new per-track gain offsets +
  // (v0.25.0) per-clip overrides. Reuses every cached TTS / SFX /
  // image asset; only re-runs concat + ducking + master loudnorm
  // so it completes in seconds even on a multi-hour audiobook.
  remix: (
    audiobookId: string,
    payload: {
      voice_db?: number;
      music_db?: number;
      sfx_db?: number;
      voice_mute?: boolean;
      music_mute?: boolean;
      sfx_mute?: boolean;
      clips?: Record<string, { gain_db?: number; mute?: boolean }>;
    },
  ) =>
    post<{
      message: string;
      audiobook_id: string;
      track_mix: Record<string, number | boolean | object>;
    }>(`/api/v1/audiobooks/${audiobookId}/remix`, payload),

  // List every cached audio clip — drives the multi-track timeline
  // editor (v0.25.0).
  listClips: (audiobookId: string) =>
    get<{
      tracks: {
        voice: AudiobookClip[];
        sfx: AudiobookClip[];
        music: AudiobookClip[];
      };
      overrides: Record<string, { gain_db?: number; mute?: boolean }>;
    }>(`/api/v1/audiobooks/${audiobookId}/clips`),

  createAI: (data: {
    concept: string;
    characters: Array<{
      name: string;
      description: string;
      gender: string;
      voice_profile_id: string | null;
    }>;
    target_minutes: number;
    mood: string;
    output_format: string;
    music_enabled: boolean;
    music_mood?: string;
    music_volume_db?: number;
    speed: number;
    pitch: number;
    image_generation_enabled?: boolean;
    per_chapter_music?: boolean;
  }) =>
    post<{ audiobook_id: string; status: string; title: string }>(
      '/api/v1/audiobooks/create-ai',
      data,
    ),

  uploadToYouTube: (id: string, data: { title: string; description: string; tags: string[]; privacy_status: string }) =>
    post<{ status: string; youtube_video_id: string; youtube_url: string }>(
      `/api/v1/audiobooks/${id}/upload-youtube`,
      data,
    ),

  updateSettings: (id: string, data: { output_format?: string; music_enabled?: boolean; music_mood?: string; speed?: number; pitch?: number; video_orientation?: string; caption_style_preset?: string | null; image_generation_enabled?: boolean; per_chapter_music?: boolean }) =>
    put<Audiobook>(`/api/v1/audiobooks/${id}`, data),
};

// ---------------------------------------------------------------------------
// Metrics
// ---------------------------------------------------------------------------

export const metricsApi = {
  events: (limit = 100) =>
    get<Array<{
      step: string;
      duration_seconds: number;
      success: boolean;
      episode_id: string;
      timestamp: string;
    }>>(`/api/v1/metrics/events?limit=${limit}`),
};

// ---------------------------------------------------------------------------
// App Events (structured log file reader)
// ---------------------------------------------------------------------------

export type AppEventLevel = 'warning' | 'error' | 'critical';

export interface AppLogEvent {
  timestamp: string;
  level: AppEventLevel;
  logger: string;
  event: string;
  context: Record<string, unknown>;
}

export interface AppEventsResponse {
  events: AppLogEvent[];
}

export const eventsApi = {
  list: (limit = 200, minLevel: AppEventLevel = 'warning') =>
    get<AppEventsResponse>(
      `/api/v1/events?limit=${limit}&min_level=${minLevel}`,
    ),
};

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

export const settings = {
  storage: () => get<StorageUsage>('/api/v1/settings/storage'),

  health: () => get<HealthCheck>('/api/v1/settings/health'),

  ffmpeg: () => get<FFmpegInfo>('/api/v1/settings/ffmpeg'),
};

// ---------------------------------------------------------------------------
// API Keys
// ---------------------------------------------------------------------------

export const apiKeys = {
  list: () =>
    get<Array<{ key_name: string; created_at: string; updated_at: string }>>(
      '/api/v1/settings/api-keys',
    ),

  store: (keyName: string, apiKey: string) =>
    post<{ message: string; key_name: string }>(
      '/api/v1/settings/api-keys',
      { key_name: keyName, api_key: apiKey },
    ),

  remove: (keyName: string) =>
    del(`/api/v1/settings/api-keys/${keyName}`),

  integrations: () =>
    get<Record<string, { configured: boolean; source: string }>>(
      '/api/v1/settings/integrations',
    ),
};

// ---------------------------------------------------------------------------
// RunPod Cloud GPU
// ---------------------------------------------------------------------------

export const runpod = {
  listPods: () =>
    get<any[]>('/api/v1/runpod/pods'),

  createPod: (data: {
    name: string;
    gpu_type_id?: string;
    image?: string;
    gpu_count?: number;
    volume_gb?: number;
    ports?: string;
    template_id?: string;
    env?: Record<string, string>;
    docker_args?: string;
  }) =>
    post<any>('/api/v1/runpod/pods', data),

  startPod: (podId: string) =>
    post<any>(`/api/v1/runpod/pods/${podId}/start`),

  stopPod: (podId: string) =>
    post<any>(`/api/v1/runpod/pods/${podId}/stop`),

  deletePod: (podId: string) =>
    del(`/api/v1/runpod/pods/${podId}`),

  gpuTypes: () =>
    get<any[]>('/api/v1/runpod/gpu-types'),

  registerPod: (podId: string, port?: number) =>
    post<any>(`/api/v1/runpod/pods/${podId}/register`, {
      comfyui_port: port ?? 8188,
    }),

  deployStatus: (podId: string) =>
    get<{ pod_id: string; status: string; message: string; registered?: boolean; service_url?: string; model_name?: string; pod_type?: string }>(
      `/api/v1/runpod/pods/${podId}/deploy-status`,
    ),
};

// ---------------------------------------------------------------------------
// Social Media Platforms
// ---------------------------------------------------------------------------

export interface SocialPlatform {
  id: string;
  platform: string;
  account_name: string | null;
  is_active: boolean;
  created_at: string;
}

export interface SocialUpload {
  id: string;
  platform: string;
  content_type: string;
  title: string;
  remote_url: string | null;
  upload_status: string;
  views: number;
  likes: number;
  comments: number;
  shares: number;
  created_at: string;
}

export interface SocialPlatformStats {
  platform: string;
  total_uploads: number;
  total_views: number;
  total_likes: number;
  total_comments: number;
  total_shares: number;
}

export const social = {
  listPlatforms: () =>
    get<SocialPlatform[]>('/api/v1/social/platforms'),

  connectPlatform: (data: {
    platform: string;
    account_name: string;
    account_id?: string;
    access_token: string;
    refresh_token?: string;
    account_metadata?: Record<string, string>;
  }) => post<SocialPlatform>('/api/v1/social/platforms', data),

  disconnectPlatform: (platformId: string) =>
    del(`/api/v1/social/platforms/${platformId}`),

  listUploads: () =>
    get<SocialUpload[]>('/api/v1/social/uploads'),

  getStats: () =>
    get<SocialPlatformStats[]>('/api/v1/social/stats'),

  // TikTok OAuth
  tiktokAuthUrl: () =>
    get<{ auth_url: string; state: string }>('/api/v1/social/tiktok/auth-url'),

  tiktokStatus: () =>
    get<{ connected: boolean; account: SocialPlatform | null }>('/api/v1/social/tiktok/status'),
};

// ---------------------------------------------------------------------------
// YouTube
// ---------------------------------------------------------------------------

export const youtube = {
  getAuthUrl: () =>
    get<{ auth_url: string }>('/api/v1/youtube/auth-url'),

  getStatus: () =>
    get<{ connected: boolean; channel: YouTubeChannel | null; channels: YouTubeChannel[] }>(
      '/api/v1/youtube/status',
    ),

  listChannels: () =>
    get<YouTubeChannel[]>('/api/v1/youtube/channels'),

  updateChannel: (channelId: string, data: { upload_days?: string[] | null; upload_time?: string | null }) =>
    put<YouTubeChannel>(`/api/v1/youtube/channels/${channelId}`, data),

  disconnect: (channelId?: string) =>
    post<{ message: string }>(`/api/v1/youtube/disconnect${channelId ? `?channel_id=${channelId}` : ''}`, {}),

  // Hard-delete a channel row plus its cascaded uploads. Use when the
  // user wants the channel gone for good rather than merely
  // disconnected (tokens cleared, row kept).
  deleteChannel: (channelId: string) =>
    del<{ message: string }>(`/api/v1/youtube/channels/${channelId}`),

  upload: (episodeId: string, data: YouTubeUploadRequest) =>
    post<YouTubeUpload>(`/api/v1/youtube/upload/${episodeId}`, data),

  getUploads: (limit = 1000) =>
    get<YouTubeUpload[]>(`/api/v1/youtube/uploads?limit=${limit}`),

  // Surface duplicate ``done`` uploads grouped by (episode_id, channel_id).
  // The earliest row is treated as canonical; ``duplicates`` lists the
  // superseded rows. Use before calling ``dedupeUploads`` so the
  // operator can preview what's about to change.
  listDuplicateUploads: () =>
    get<{
      count: number;
      groups: Array<{
        episode_id: string;
        channel_id: string;
        keep: { upload_id: string; video_id: string | null };
        duplicates: Array<{
          upload_id: string;
          video_id: string | null;
          created_at: string | null;
        }>;
      }>;
    }>('/api/v1/youtube/uploads/duplicates'),

  // Idempotent — keeps the earliest done row, marks the rest failed,
  // and (when delete_on_youtube=true) deletes the duplicate videos via
  // the YouTube Data API. Returns counts + per-group summary.
  dedupeUploads: (deleteOnYoutube = true) =>
    post<{
      groups: number;
      rows_marked_failed: number;
      videos_deleted: number;
      delete_errors: string[];
      summary: Array<{
        episode_id: string;
        channel_id: string;
        kept_upload_id: string;
        kept_video_id: string | null;
        removed: Array<{ upload_id: string; video_id: string | null }>;
      }>;
    }>(`/api/v1/youtube/uploads/dedupe?delete_on_youtube=${deleteOnYoutube}`),

  // Playlists — when ``channelId`` is omitted AND the install has
  // multiple connected channels, the backend returns 400 with the
  // full channel list so the caller can pick. v0.20.18 plumbed
  // ``channelId`` through every scoped endpoint.
  listPlaylists: (channelId?: string) =>
    get<YouTubePlaylist[]>(
      `/api/v1/youtube/playlists${channelId ? `?channel_id=${channelId}` : ''}`,
    ),

  createPlaylist: (
    data: { title: string; description?: string; privacy_status?: string },
    channelId?: string,
  ) =>
    post<YouTubePlaylist>(
      `/api/v1/youtube/playlists${channelId ? `?channel_id=${channelId}` : ''}`,
      data,
    ),

  addToPlaylist: (playlistId: string, videoId: string) =>
    post<{ message: string }>(`/api/v1/youtube/playlists/${playlistId}/add`, { video_id: videoId }),

  deletePlaylist: (playlistId: string) =>
    del(`/api/v1/youtube/playlists/${playlistId}`),

  // Analytics
  getVideoStats: (videoIds: string[], channelId?: string) => {
    const params = new URLSearchParams();
    params.set('video_ids', videoIds.join(','));
    if (channelId) params.set('channel_id', channelId);
    return get<YouTubeVideoStats[]>(`/api/v1/youtube/analytics?${params.toString()}`);
  },

  getChannelAnalytics: (params?: { channelId?: string; days?: number }) => {
    const qs = new URLSearchParams();
    if (params?.channelId) qs.set('channel_id', params.channelId);
    if (params?.days) qs.set('days', String(params.days));
    const q = qs.toString();
    return get<YouTubeChannelAnalytics>(
      `/api/v1/youtube/analytics/channel${q ? `?${q}` : ''}`,
    );
  },

};

export interface YouTubeChannelAnalytics {
  channel_id: string;
  window_days: number;
  start_date: string;
  end_date: string;
  totals: {
    views: number;
    estimated_minutes_watched: number;
    average_view_duration_seconds: number;
    subscribers_gained: number;
    subscribers_lost: number;
    likes: number;
    comments: number;
    shares: number;
    card_click_rate: number;
    card_impressions: number;
  };
  daily: { day: string; views: number; minutes_watched: number }[];
}

// ---------------------------------------------------------------------------
// Video Templates
// ---------------------------------------------------------------------------

// First call site that pulls a generated schema from ``types/api.d.ts``.
// Pattern (to be repeated as ``any`` is paid down in this file):
//
//   import type { components } from '@/types/api';
//   type Foo = components['schemas']['FooResponse'];
//
// The hand-rolled types in ``types/index.ts`` stay around for now —
// migration is opt-in per call site. See CLAUDE.md → Generated API
// Types for the regen workflow.
type VideoTemplateResponse = ApiSchema['VideoTemplateResponse'];
type VideoTemplateCreate = ApiSchema['VideoTemplateCreate'];
type VideoTemplateUpdate = ApiSchema['VideoTemplateUpdate'];

export const videoTemplates = {
  list: () => get<VideoTemplateResponse[]>('/api/v1/video-templates'),
  create: (data: VideoTemplateCreate) =>
    post<VideoTemplateResponse>('/api/v1/video-templates', data),
  update: (id: string, data: VideoTemplateUpdate) =>
    put<VideoTemplateResponse>(`/api/v1/video-templates/${id}`, data),
  remove: (id: string) => del(`/api/v1/video-templates/${id}`),
  applyToSeries: (templateId: string, seriesId: string) =>
    post<VideoTemplateResponse>(
      `/api/v1/video-templates/${templateId}/apply/${seriesId}`,
    ),
  fromSeries: (seriesId: string) =>
    post<VideoTemplateResponse>(`/api/v1/video-templates/from-series/${seriesId}`),
};

// ---------------------------------------------------------------------------
// Schedule
// ---------------------------------------------------------------------------

export const schedule = {
  list: (status?: string) => {
    const qs = status ? `?status=${status}` : '';
    return get<any[]>(`/api/v1/schedule${qs}`);
  },
  calendar: (start: string, end: string) =>
    get<any>(`/api/v1/schedule/calendar?start=${start}&end=${end}`),
  create: (data: {
    content_type: string;
    content_id: string;
    platform: string;
    scheduled_at: string;
    title: string;
    description?: string;
    tags?: string;
    privacy?: string;
  }) => post<any>('/api/v1/schedule', data),
  cancel: (id: string) => del(`/api/v1/schedule/${id}`),
  update: (id: string, data: any) => put<any>(`/api/v1/schedule/${id}`, data),
  // Auto-schedule a series (v0.26.x)
  autoScheduleSeries: (
    seriesId: string,
    body: {
      cadence: 'daily' | 'every_n_days' | 'weekly';
      every_n?: number;
      start_at: string;
      episode_filter?: 'review' | 'all_unuploaded';
      privacy?: 'public' | 'unlisted' | 'private';
      description_template?: string;
      tags_template?: string;
      youtube_channel_id?: string | null;
      dry_run?: boolean;
    },
  ) => post<any>(`/api/v1/schedule/series/${seriesId}/auto-schedule`, body),

  // Next free slot for a single platform — UI uses this to populate
  // "next available" without making the user pick a date that may
  // clash with an existing pending post.
  nextSlot: (params: {
    platform: 'youtube' | 'tiktok' | 'instagram' | 'facebook' | 'x';
    channelId?: string;
    excludeWindowMinutes?: number;
  }) => {
    const qs = new URLSearchParams({ platform: params.platform });
    if (params.channelId) qs.set('channel_id', params.channelId);
    if (params.excludeWindowMinutes !== undefined) {
      qs.set('exclude_window_minutes', String(params.excludeWindowMinutes));
    }
    return get<{ platform: string; scheduled_at: string }>(
      `/api/v1/schedule/next-slot?${qs.toString()}`,
    );
  },
};

// ---------------------------------------------------------------------------
// License
// ---------------------------------------------------------------------------

export interface LicenseStatus {
  state: 'unactivated' | 'active' | 'grace' | 'expired' | 'invalid';
  tier: string | null;
  features: string[];
  machines_cap: number | null;
  machine_id: string;
  activated_at: string | null;
  last_heartbeat_at: string | null;
  last_heartbeat_status: string | null;
  period_end: string | null;
  exp: string | null;
  error: string | null;
  // New for Lifetime (Pro) support. Older backends that haven't been
  // updated yet won't send these fields, which is fine — every consumer
  // treats them as optional.
  license_type?: 'subscription' | 'lifetime_pro' | null;
  update_window_expires_at?: string | null;
}

export interface ActivationEntry {
  machine_id: string;
  first_seen: number | null;
  last_heartbeat: number | null;
  last_known_version: string | null;
  is_this_machine: boolean;
}

export interface ActivationsResponse {
  tier: string;
  cap: number;
  this_machine_id: string;
  activations: ActivationEntry[];
}

export const license = {
  status: () => get<LicenseStatus>('/api/v1/license/status'),
  // Today's episode-generation usage against the tier's daily cap.
  // ``limit`` is null for unlimited tiers; the Dashboard's QuotaWidget
  // renders the "∞" symbol in that case.
  quota: () =>
    get<{ used: number; limit: number | null }>('/api/v1/license/quota'),
  activate: (license_jwt: string) =>
    post<LicenseStatus>('/api/v1/license/activate', { license_jwt }),
  deactivate: () => post<LicenseStatus>('/api/v1/license/deactivate'),
  portal: () => post<{ url: string }>('/api/v1/license/portal'),
  listActivations: () =>
    get<ActivationsResponse>('/api/v1/license/activations'),
  deactivateMachine: (machine_id: string) =>
    post<ActivationsResponse>(
      `/api/v1/license/activations/${encodeURIComponent(machine_id)}/deactivate`,
    ),
  // Seat management without a local activation (used by the activation
  // wizard to recover from the seat-cap lockout).
  listActivationsByKey: (license_key: string) =>
    post<ActivationsResponse>('/api/v1/license/activations/query', { license_key }),
  freeSeatByKey: (license_key: string, machine_id: string) =>
    post<ActivationsResponse>('/api/v1/license/activations/free-seat', {
      license_key,
      machine_id,
    }),
};

// ---------------------------------------------------------------------------
// Updates
// ---------------------------------------------------------------------------

export interface UpdateStatus {
  current_installed: string | null;
  current_stable: string | null;
  update_available: boolean;
  mandatory_security_update: boolean;
  changelog_url: string | null;
  image_tags: Record<string, string>;
  unavailable: boolean;
  reason: string | null;
}

export interface UpdateProgress {
  phase: 'idle' | 'pulling' | 'pulled' | 'restarting' | 'done' | 'failed' | string;
  detail: string;
  ts: string;
  started_at: string;
}

export interface ChangelogEntry {
  version: string;
  name: string;
  body: string;
  published_at: string | null;
  html_url: string | null;
  is_prerelease: boolean;
}

export interface ChangelogResponse {
  entries: ChangelogEntry[];
  cached: boolean;
  source: string;
  error: string | null;
}

export const updates = {
  status: (force: boolean = false) =>
    get<UpdateStatus>(`/api/v1/updates/status${force ? '?force=true' : ''}`),
  apply: () => post<{ queued: boolean; hint: string }>('/api/v1/updates/apply'),
  progress: () => get<UpdateProgress>('/api/v1/updates/progress'),
  changelog: (force: boolean = false, limit: number = 20) =>
    get<ChangelogResponse>(
      `/api/v1/updates/changelog?limit=${limit}${force ? '&force=true' : ''}`,
    ),
};

// ---------------------------------------------------------------------------
// A/B tests
// ---------------------------------------------------------------------------

export interface ABTest {
  id: string;
  series_id: string;
  episode_a_id: string;
  episode_b_id: string;
  variant_label: string;
  notes: string | null;
  winner_episode_id: string | null;
  comparison_at: string | null;
  created_at: string;
}

export interface ABTestStats {
  episode_id: string;
  title: string;
  status: string;
  youtube_video_id: string | null;
  youtube_url: string | null;
  youtube_views: number | null;
  youtube_likes: number | null;
  youtube_comments: number | null;
}

export interface ABTestDetail extends ABTest {
  episode_a_stats: ABTestStats;
  episode_b_stats: ABTestStats;
}

export const abTests = {
  list: (seriesId?: string) => {
    const qs = seriesId ? `?series_id=${seriesId}` : '';
    return get<ABTest[]>(`/api/v1/ab-tests${qs}`);
  },
  get: (id: string) => get<ABTestDetail>(`/api/v1/ab-tests/${id}`),
  create: (data: {
    series_id: string;
    episode_a_id: string;
    episode_b_id: string;
    variant_label: string;
    notes?: string;
  }) => post<ABTest>('/api/v1/ab-tests', data),
  remove: (id: string) => del(`/api/v1/ab-tests/${id}`),
};

// ---------------------------------------------------------------------------
// SEO score
// ---------------------------------------------------------------------------

export interface SEOCheck {
  id: string;
  label: string;
  pass: boolean;
  severity: 'ok' | 'warn' | 'error' | 'info';
  hint: string;
}

export interface SEOScore {
  overall_score: number;
  grade: 'A' | 'B' | 'C' | 'D';
  summary: string;
  has_seo_metadata: boolean;
  checks: SEOCheck[];
}

// ---------------------------------------------------------------------------
// Onboarding
// ---------------------------------------------------------------------------

export interface OnboardingStatus {
  comfyui_servers: number;
  llm_configs: number;
  voice_profiles: number;
  youtube_channels: number;
  dismissed: boolean;
  should_show: boolean;
}

export const onboarding = {
  status: () => get<OnboardingStatus>('/api/v1/onboarding/status'),
  dismiss: () => post<void>('/api/v1/onboarding/dismiss'),
  reset: () => post<void>('/api/v1/onboarding/reset'),
};

// ---------------------------------------------------------------------------
// Auth / users
// ---------------------------------------------------------------------------

export interface AuthUser {
  id: string;
  email: string;
  role: 'owner' | 'editor' | 'viewer';
  display_name: string | null;
  is_active: boolean;
  last_login_at: string | null;
  /** True when TOTP 2FA has been confirmed (totp_confirmed_at IS NOT NULL). */
  totp_enabled: boolean;
}

export interface LoginResponse {
  message: string;
  role: string;
  display_name: string;
}

/** Returned by POST /auth/login when the user has confirmed 2FA. */
export interface TotpChallengeResponse {
  stage: 'totp_required';
  challenge: string;
}

/** Union of the two possible login outcomes. */
export type LoginOrTotpResponse = LoginResponse | TotpChallengeResponse;

export interface TotpEnrollResponse {
  secret_base32: string;
  otpauth_uri: string;
  recovery_codes: string[];
}

export interface UserCreate {
  email: string;
  password: string;
  role?: 'owner' | 'editor' | 'viewer';
  display_name?: string | null;
}

export interface UserUpdate {
  role?: 'owner' | 'editor' | 'viewer';
  display_name?: string | null;
  is_active?: boolean;
  password?: string;
}

// A.2 — login event row returned by /auth/login-history
export interface LoginEvent {
  id: string;
  timestamp: string;
  ip: string;
  user_agent: string | null;
  success: boolean;
  failure_reason: string | null;
}

export const auth = {
  /**
   * Stage-1 login. Returns either:
   * - {message, role, display_name}    — password-only success (no 2FA).
   * - {stage: "totp_required", challenge} — 2FA required, complete via loginTotp.
   */
  login: (email: string, password: string) =>
    post<LoginOrTotpResponse>('/api/v1/auth/login', { email, password }),
  /**
   * Stage-2 TOTP login. Pass the challenge from stage-1 plus the 6-digit
   * code (or 16-char recovery code). Issues the session cookie on success.
   */
  loginTotp: (challenge: string, code: string) =>
    post<LoginResponse>('/api/v1/auth/login/totp', { challenge, code }),
  logout: () => post<{ message: string }>('/api/v1/auth/logout'),
  // A.3 — invalidate all sessions for the current user on all devices.
  logoutEverywhere: () => post<{ message: string }>('/api/v1/auth/logout-everywhere'),
  me: () => get<AuthUser | null>('/api/v1/auth/me'),
  mode: () => get<{ team_mode: boolean; demo_mode?: boolean }>('/api/v1/auth/mode'),
  // A.2 — recent login events for the current user.
  loginHistory: (limit = 20) =>
    get<LoginEvent[]>(`/api/v1/auth/login-history?limit=${limit}`),
  // Per-user UI preferences (dashboard layout, theme, calendar view, …).
  // PUT does a shallow merge: top-level keys present in the body
  // overwrite, ``null`` deletes, omitted keys are left as-is.
  getPreferences: () =>
    get<Record<string, unknown>>('/api/v1/auth/preferences'),
  updatePreferences: (patch: Record<string, unknown>) =>
    put<Record<string, unknown>>('/api/v1/auth/preferences', patch),
  // ── TOTP 2FA ────────────────────────────────────────────────────────
  /** Generate secret + recovery codes. Shows recovery codes once. */
  enrollTotp: () => post<TotpEnrollResponse>('/api/v1/auth/2fa/enroll'),
  /** Verify first TOTP code from authenticator app → activates 2FA. */
  confirmTotp: (code: string) =>
    post<{ message: string }>('/api/v1/auth/2fa/confirm', { code }),
  /** Disable 2FA after re-entering password. */
  disableTotp: (password: string) =>
    post<{ message: string }>('/api/v1/auth/2fa/disable', { password }),
  /**
   * Request a password-reset email.
   * Always returns the same generic message regardless of whether the
   * email is registered (enumeration-safe).
   */
  forgotPassword: (email: string) =>
    post<{ message: string }>('/api/v1/auth/forgot-password', { email }),
  /**
   * Consume a reset token and set a new password.
   * Returns either:
   * - {message: "password_reset_successful"}             — no 2FA, done.
   * - {stage: "totp_required", challenge: string}        — 2FA required.
   */
  resetPassword: (token: string, password: string, totpCode?: string) =>
    post<{ message: string } | TotpChallengeResponse>(
      '/api/v1/auth/reset-password',
      { token, new_password: password, ...(totpCode ? { totp_code: totpCode } : {}) },
    ),
};

export const users = {
  list: () => get<AuthUser[]>('/api/v1/users'),
  create: (data: UserCreate) => post<AuthUser>('/api/v1/users', data),
  update: (id: string, data: UserUpdate) =>
    put<AuthUser>(`/api/v1/users/${id}`, data),
  delete: (id: string) => del(`/api/v1/users/${id}`),
  // A.2 — owner can fetch login history for any user.
  loginHistory: (userId: string, limit = 20) =>
    get<LoginEvent[]>(`/api/v1/users/${userId}/login-history?limit=${limit}`),
};

// ---------------------------------------------------------------------------
// Assets (central media library) + video ingest
// ---------------------------------------------------------------------------

export type AssetKind = 'image' | 'video' | 'audio' | 'other';

export interface Asset {
  id: string;
  kind: AssetKind;
  filename: string;
  file_path: string;
  file_size_bytes: number;
  mime_type: string | null;
  hash_sha256: string;
  width: number | null;
  height: number | null;
  duration_seconds: number | null;
  tags: string[];
  description: string | null;
  created_at: string;
}

export interface CandidateClip {
  start_s: number;
  end_s: number;
  title: string;
  reason: string;
  score: number;
}

export interface VideoIngestJob {
  id: string;
  asset_id: string;
  status: 'queued' | 'running' | 'done' | 'failed';
  stage: string | null;
  progress_pct: number;
  candidate_clips: CandidateClip[] | null;
  selected_clip_index: number | null;
  resulting_episode_id: string | null;
  error_message: string | null;
}

async function uploadMultipart<T>(path: string, form: FormData): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'POST',
    body: form,
    credentials: 'same-origin',
  });
  if (!res.ok) {
    let detail: string | undefined;
    let detailRaw: unknown;
    try {
      const body = await res.json();
      detailRaw = body?.detail ?? body;
      detail = typeof body?.detail === 'string' ? body.detail : JSON.stringify(body);
    } catch {
      detail = res.statusText;
    }
    throw new ApiError(res.status, res.statusText, detail, detailRaw);
  }
  return res.json() as Promise<T>;
}

export const assets = {
  list: (params?: { kind?: AssetKind; search?: string; tag?: string; limit?: number }) => {
    const q = new URLSearchParams();
    if (params?.kind) q.set('kind', params.kind);
    if (params?.search) q.set('search', params.search);
    if (params?.tag) q.set('tag', params.tag);
    q.set('limit', String(params?.limit ?? 200));
    return get<Asset[]>(`/api/v1/assets?${q.toString()}`);
  },
  get: (id: string) => get<Asset>(`/api/v1/assets/${id}`),
  upload: (file: File, opts?: { tags?: string[]; description?: string }) => {
    const form = new FormData();
    form.append('file', file);
    if (opts?.tags?.length) form.append('tags', opts.tags.join(','));
    if (opts?.description) form.append('description', opts.description);
    return uploadMultipart<Asset>('/api/v1/assets', form);
  },
  update: (id: string, data: { tags?: string[]; description?: string }) =>
    request<Asset>(`/api/v1/assets/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  delete: (id: string) => del(`/api/v1/assets/${id}`),
  fileUrl: (id: string) => `${BASE_URL}/api/v1/assets/${id}/file`,
};

export const videoIngest = {
  start: (file: File, description?: string) => {
    const form = new FormData();
    form.append('file', file);
    if (description) form.append('description', description);
    return uploadMultipart<VideoIngestJob>('/api/v1/video-ingest', form);
  },
  get: (jobId: string) => get<VideoIngestJob>(`/api/v1/video-ingest/${jobId}`),
  pick: (jobId: string, clipIndex: number, seriesId: string) =>
    post<{ status: string }>(`/api/v1/video-ingest/${jobId}/pick`, {
      clip_index: clipIndex,
      series_id: seriesId,
    }),
};

// ---------------------------------------------------------------------------
// Video editor sessions (Phase D)
// ---------------------------------------------------------------------------

export interface EditTimelineClip {
  id: string;
  scene_number?: number;
  source?: string;
  asset_path?: string | null;
  asset_id?: string | null;
  in_s: number;
  out_s: number;
  start_s: number;
  end_s: number;
  speed?: number;
  gain_db?: number;
  duck_to_voice?: boolean;
  // Overlay-track fields (kind=overlay clips only)
  kind?: 'text' | 'shape' | 'image';
  text?: string;
  font_size?: number;
  color?: string;
  box?: boolean;
  box_color?: string;
  shape?: 'rect' | 'circle';
  w?: number;
  h?: number;
  x?: string | number;
  y?: string | number;
  // Audio envelope points [(t, gain_db), ...]
  envelope?: Array<[number, number]>;
}

export interface EditTimelineTrack {
  id: string;
  kind: 'video' | 'audio' | 'overlay' | 'captions';
  clips: EditTimelineClip[];
}

export interface EditTimeline {
  duration_s: number;
  tracks: EditTimelineTrack[];
}

export interface EditSession {
  id: string;
  episode_id: string;
  version: number;
  timeline: EditTimeline;
  last_render_job_id: string | null;
  last_rendered_at: string | null;
  // v0.20.20 — the finalized video path if the episode was already
  // assembled. PreviewPlayer uses it as the default source so users
  // can see their finished episode immediately instead of a black
  // rectangle + "no scene at this position".
  final_video_path?: string | null;
}

export interface CaptionWord {
  word: string;
  start_seconds: number;
  end_seconds: number;
  emphasis?: boolean;
  color?: string | null;
}

export const editor = {
  get: (episodeId: string) => get<EditSession>(`/api/v1/episodes/${episodeId}/editor`),
  save: (episodeId: string, timeline: EditTimeline) =>
    put<EditSession>(`/api/v1/episodes/${episodeId}/editor`, { timeline }),
  render: (episodeId: string) =>
    post<{ status: string }>(`/api/v1/episodes/${episodeId}/editor/render`),
  preview: (episodeId: string) =>
    post<{ status: string }>(`/api/v1/episodes/${episodeId}/editor/preview`),
  getCaptions: (episodeId: string) =>
    get<{ words: CaptionWord[] }>(`/api/v1/episodes/${episodeId}/editor/captions`),
  putCaptions: (episodeId: string, words: CaptionWord[]) =>
    put<{ words: CaptionWord[] }>(`/api/v1/episodes/${episodeId}/editor/captions`, { words }),
  waveformUrl: (episodeId: string, track: 'voice' | 'music') =>
    `/api/v1/episodes/${episodeId}/editor/waveform?track=${track}`,
};

// ---------------------------------------------------------------------------
// Character Packs
// ---------------------------------------------------------------------------

export const characterPacks = {
  list: () => get<CharacterPack[]>('/api/v1/character-packs'),

  create: (data: CharacterPackCreate) =>
    post<CharacterPack>('/api/v1/character-packs', data),

  delete: (id: string) => del(`/api/v1/character-packs/${id}`),

  apply: (packId: string, seriesId: string) =>
    post<Record<string, unknown>>(
      `/api/v1/character-packs/${packId}/apply`,
      { series_id: seriesId },
    ),
};
