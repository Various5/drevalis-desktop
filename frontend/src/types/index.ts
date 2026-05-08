// =============================================================================
// Drevalis Creator Studio TypeScript Interfaces
// Mirrors backend Pydantic schemas for full type safety.
// =============================================================================

// ---------------------------------------------------------------------------
// Caption Style
// ---------------------------------------------------------------------------

export interface CaptionStyle {
  preset: 'youtube_highlight' | 'karaoke' | 'tiktok_pop' | 'minimal' | 'classic';
  font_name: string;
  font_size: number;
  primary_color: string;  // hex #RRGGBB
  highlight_color: string;
  outline_color: string;
  outline_width: number;
  position: 'bottom' | 'center' | 'top';
  margin_v: number;
  animation: 'fade' | 'pop' | 'bounce' | 'none';
  words_per_line: number;
  uppercase: boolean;
}

// ---------------------------------------------------------------------------
// Series
// ---------------------------------------------------------------------------

export interface ToneProfile {
  persona?: string;
  forbidden_words?: string[];
  required_moves?: string[];
  reading_level?: number;
  max_sentence_words?: number;
  style_sample?: string | null;
  signature_phrases?: string[];
  allow_listicle?: boolean;
  cta_boilerplate?: boolean;
}

export interface SeriesCreate {
  name: string;
  description?: string | null;
  voice_profile_id?: string | null;
  comfyui_server_id?: string | null;
  comfyui_workflow_id?: string | null;
  llm_config_id?: string | null;
  script_prompt_template_id?: string | null;
  visual_prompt_template_id?: string | null;
  visual_style?: string;
  character_description?: string;
  target_duration_seconds?: 15 | 30 | 60;
  default_language?: string;
  caption_style?: CaptionStyle;
  scene_mode?: 'image' | 'video';
  music_mood?: string;
  music_volume_db?: number;
  music_enabled?: boolean;
  video_comfyui_workflow_id?: string;
  tone_profile?: ToneProfile | null;
}

export interface SeriesUpdate {
  name?: string | null;
  description?: string | null;
  voice_profile_id?: string | null;
  comfyui_server_id?: string | null;
  comfyui_workflow_id?: string | null;
  llm_config_id?: string | null;
  script_prompt_template_id?: string | null;
  visual_prompt_template_id?: string | null;
  visual_style?: string | null;
  character_description?: string | null;
  target_duration_seconds?: 15 | 30 | 60 | null;
  default_language?: string | null;
  caption_style?: CaptionStyle | null;
  scene_mode?: 'image' | 'video' | null;
  music_mood?: string | null;
  music_volume_db?: number | null;
  music_enabled?: boolean | null;
  video_comfyui_workflow_id?: string | null;
  youtube_channel_id?: string | null;
  content_format?: 'shorts' | 'longform' | 'music_video' | null;
  target_duration_minutes?: number | null;
  chapter_enabled?: boolean | null;
  scenes_per_chapter?: number | null;
  transition_style?: string | null;
  transition_duration?: number | null;
  duration_match_strategy?: string | null;
  base_seed?: number | null;
  visual_consistency_prompt?: string | null;
  aspect_ratio?: string | null;
  tone_profile?: ToneProfile | null;
}

export interface Series {
  id: string;
  name: string;
  description: string | null;
  voice_profile_id: string | null;
  comfyui_server_id: string | null;
  comfyui_workflow_id: string | null;
  llm_config_id: string | null;
  script_prompt_template_id: string | null;
  visual_prompt_template_id: string | null;
  visual_style: string | null;
  character_description: string | null;
  target_duration_seconds: number;
  default_language: string;
  caption_style: CaptionStyle | null;
  scene_mode: 'image' | 'video';
  music_mood: string | null;
  music_volume_db: number;
  music_enabled: boolean;
  video_comfyui_workflow_id: string | null;
  youtube_channel_id: string | null;
  content_format: 'shorts' | 'longform' | 'music_video';
  target_duration_minutes: number | null;
  chapter_enabled: boolean;
  scenes_per_chapter: number;
  transition_style: string | null;
  transition_duration: number;
  duration_match_strategy: string;
  base_seed: number | null;
  intro_template: Record<string, unknown> | null;
  outro_template: Record<string, unknown> | null;
  visual_consistency_prompt: string | null;
  aspect_ratio: string;
  tone_profile: ToneProfile;
  created_at: string;
  updated_at: string;
}

export interface SeriesListItem {
  id: string;
  name: string;
  description: string | null;
  target_duration_seconds: number;
  episode_count: number;
  created_at: string;
}

export interface SeriesGenerateResponse {
  series_id: string;
  series_name: string;
  episode_count: number;
  episodes: Array<{ title: string; topic: string }>;
}

// ---------------------------------------------------------------------------
// Episode
// ---------------------------------------------------------------------------

export type EpisodeStatus =
  | 'draft'
  | 'generating'
  | 'review'
  | 'editing'
  | 'exported'
  | 'failed';

export interface EpisodeCreate {
  series_id: string;
  title: string;
  topic?: string | null;
}

export interface EpisodeUpdate {
  title?: string | null;
  topic?: string | null;
  script?: Record<string, unknown> | null;
  status?: EpisodeStatus | null;
  override_voice_profile_id?: string | null;
  override_llm_config_id?: string | null;
  override_caption_style?: string | null;
}

export interface MediaAsset {
  id: string;
  asset_type: string;
  file_path: string;
  file_size_bytes: number | null;
  duration_seconds: number | null;
  scene_number: number | null;
  generation_job_id: string | null;
  created_at: string;
}

export interface GenerationJobBrief {
  id: string;
  step: string;
  status: string;
  progress_pct: number;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  retry_count: number;
  created_at: string;
}

/**
 * Subset of ``episode.metadata_['seo']`` written by the SEO generation
 * job (``services/youtube_admin.py:get_or_generate_seo`` and the
 * background ``workers/jobs/seo.py:generate_seo_async``). Both call
 * sites populate the same shape; this interface mirrors the union.
 *
 * TODO(backend): emit a Pydantic ``SEOMetadata`` schema and replace
 * this mirror with the OpenAPI-generated type in Phase 6.
 */
export interface SEOMetadata {
  title?: string;
  description?: string;
  hashtags?: string[];
  tags?: string[];
  /** Background job only; absent on the inline upload-time call. */
  hook?: string;
  /** Background job only. 1-10 score. */
  virality_score?: number;
  virality_reasoning?: string;
}

/**
 * Free-form metadata bag. Known keys carry typed values; unknown keys
 * fall back to ``unknown`` so casts are forced at the use site (rather
 * than silently turning into ``any``).
 */
export interface EpisodeMetadata {
  seo?: SEOMetadata;
  /** Per-episode TTS overrides written by the regenerate-voice flow. */
  tts_overrides?: { speed?: number; pitch?: number };
  [key: string]: unknown;
}

export interface Episode {
  id: string;
  series_id: string;
  title: string;
  topic: string | null;
  status: EpisodeStatus;
  script: Record<string, unknown> | null;
  base_path: string | null;
  generation_log: Record<string, unknown> | null;
  metadata_: EpisodeMetadata | null;
  override_voice_profile_id: string | null;
  override_llm_config_id: string | null;
  override_caption_style: string | null;
  created_at: string;
  updated_at: string;
  media_assets: MediaAsset[];
  generation_jobs: GenerationJobBrief[];
}

export interface EpisodeListItem {
  id: string;
  series_id: string;
  title: string;
  topic: string | null;
  status: EpisodeStatus;
  metadata_: EpisodeMetadata | null;
  created_at: string;
  updated_at: string;
}

export interface GenerateRequest {
  voice_profile_id?: string | null;
  llm_config_id?: string | null;
  steps?: PipelineStep[] | null;
}

export interface GenerateResponse {
  episode_id: string;
  job_ids: string[];
  message: string;
}

export interface RetryResponse {
  episode_id: string;
  job_id: string;
  step: string;
  message: string;
}

export interface ScriptUpdate {
  script: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Pipeline / Progress
// ---------------------------------------------------------------------------

export type PipelineStep =
  | 'script'
  | 'voice'
  | 'scenes'
  | 'captions'
  | 'assembly'
  | 'thumbnail';

export type JobStatus = 'queued' | 'running' | 'done' | 'failed';

export interface ProgressMessage {
  episode_id: string;
  job_id: string;
  step: PipelineStep;
  status: JobStatus;
  progress_pct: number;
  message: string;
  error: string | null;
  detail: Record<string, unknown> | null;
}

// ---------------------------------------------------------------------------
// Generation Jobs
// ---------------------------------------------------------------------------

export interface GenerationJob {
  id: string;
  episode_id: string;
  step: string;
  status: string;
  progress_pct: number;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  retry_count: number;
  worker_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface GenerationJobListItem {
  id: string;
  episode_id: string;
  step: string;
  status: string;
  progress_pct: number;
  error_message: string | null;
  retry_count: number;
  created_at: string;
}

export interface GenerationJobExtended {
  id: string;
  episode_id: string;
  step: string;
  status: string;
  progress_pct: number;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  retry_count: number;
  worker_id: string | null;
  created_at: string;
  updated_at: string;
  episode_title: string | null;
  series_name: string | null;
}

// ---------------------------------------------------------------------------
// Voice Profile
// ---------------------------------------------------------------------------

export interface VoiceProfileCreate {
  name: string;
  provider: 'piper' | 'elevenlabs' | 'kokoro' | 'edge' | 'comfyui_elevenlabs';
  piper_model_path?: string | null;
  piper_speaker_id?: string | null;
  speed?: number;
  pitch?: number;
  elevenlabs_voice_id?: string | null;
  sample_audio_path?: string | null;
  kokoro_voice_name?: string | null;
  kokoro_model_path?: string | null;
  edge_voice_id?: string | null;
  gender?: string | null;
  language_code?: string | null;
}

export interface VoiceProfileUpdate {
  name?: string | null;
  provider?: 'piper' | 'elevenlabs' | 'kokoro' | 'edge' | 'comfyui_elevenlabs' | null;
  piper_model_path?: string | null;
  piper_speaker_id?: string | null;
  speed?: number | null;
  pitch?: number | null;
  elevenlabs_voice_id?: string | null;
  sample_audio_path?: string | null;
  kokoro_voice_name?: string | null;
  kokoro_model_path?: string | null;
  edge_voice_id?: string | null;
}

export interface VoiceProfile {
  id: string;
  name: string;
  provider: string;
  piper_model_path: string | null;
  piper_speaker_id: string | null;
  speed: number;
  pitch: number;
  elevenlabs_voice_id: string | null;
  sample_audio_path: string | null;
  kokoro_voice_name: string | null;
  kokoro_model_path: string | null;
  edge_voice_id: string | null;
  gender: string | null;
  language_code: string | null;
  created_at: string;
  updated_at: string;
}

export interface VoiceTestResponse {
  success: boolean;
  message: string;
  audio_path: string | null;
  duration_seconds: number | null;
}

// ---------------------------------------------------------------------------
// ComfyUI
// ---------------------------------------------------------------------------

export interface ComfyUIServerCreate {
  name: string;
  url: string;
  api_key?: string | null;
  max_concurrent?: number;
  is_active?: boolean;
}

export interface ComfyUIServerUpdate {
  name?: string | null;
  url?: string | null;
  api_key?: string | null;
  max_concurrent?: number | null;
  is_active?: boolean | null;
}

export interface ComfyUIServer {
  id: string;
  name: string;
  url: string;
  has_api_key: boolean;
  max_concurrent: number;
  is_active: boolean;
  last_tested_at: string | null;
  last_test_status: string | null;
  created_at: string;
  updated_at: string;
}

export interface ComfyUIServerTestResponse {
  success: boolean;
  message: string;
  server_id: string;
}

export interface ComfyUIWorkflowCreate {
  name: string;
  description?: string | null;
  workflow_json_path: string;
  version?: number;
  input_mappings: Record<string, unknown>;
}

export interface ComfyUIWorkflowUpdate {
  name?: string | null;
  description?: string | null;
  workflow_json_path?: string | null;
  version?: number | null;
  input_mappings?: Record<string, unknown> | null;
}

export interface ComfyUIWorkflow {
  id: string;
  name: string;
  description: string | null;
  workflow_json_path: string;
  version: number;
  input_mappings: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

// ---------------------------------------------------------------------------
// LLM Config
// ---------------------------------------------------------------------------

export interface LLMConfigCreate {
  name: string;
  base_url: string;
  model_name: string;
  api_key?: string | null;
  max_tokens?: number;
  temperature?: number;
}

export interface LLMConfigUpdate {
  name?: string | null;
  base_url?: string | null;
  model_name?: string | null;
  api_key?: string | null;
  max_tokens?: number | null;
  temperature?: number | null;
}

export interface LLMConfig {
  id: string;
  name: string;
  base_url: string;
  model_name: string;
  has_api_key: boolean;
  max_tokens: number;
  temperature: number;
  created_at: string;
  updated_at: string;
}

export interface LLMTestResponse {
  success: boolean;
  message: string;
  response_text: string | null;
  model: string | null;
  tokens_used: number | null;
}

// ---------------------------------------------------------------------------
// Prompt Templates
// ---------------------------------------------------------------------------

export interface PromptTemplateCreate {
  name: string;
  template_type: 'script' | 'visual' | 'hook' | 'hashtag';
  system_prompt: string;
  user_prompt_template: string;
}

export interface PromptTemplateUpdate {
  name?: string | null;
  template_type?: 'script' | 'visual' | 'hook' | 'hashtag' | null;
  system_prompt?: string | null;
  user_prompt_template?: string | null;
}

export interface PromptTemplate {
  id: string;
  name: string;
  template_type: string;
  system_prompt: string;
  user_prompt_template: string;
  created_at: string;
  updated_at: string;
}

// ---------------------------------------------------------------------------
// Settings / Health
// ---------------------------------------------------------------------------

export interface StorageUsage {
  total_size_bytes: number;
  total_size_human: string;
  storage_base_path: string;
  storage_base_abs?: string | null;
  host_source_path?: string | null;
  subdir_sizes?: Record<string, number>;
  mountinfo_lines?: string[];
}

export interface ServiceHealth {
  name: string;
  status: 'ok' | 'degraded' | 'unreachable';
  message: string;
}

export interface HealthCheck {
  overall: 'ok' | 'degraded' | 'unhealthy';
  services: ServiceHealth[];
}

export interface FFmpegInfo {
  ffmpeg_path: string;
  available: boolean;
  version: string | null;
  message: string;
}

// ---------------------------------------------------------------------------
// Audiobook
// ---------------------------------------------------------------------------

export interface Audiobook {
  id: string;
  title: string;
  text: string;
  voice_profile_id: string | null;
  status: 'draft' | 'generating' | 'done' | 'failed';
  audio_path: string | null;
  video_path: string | null;
  duration_seconds: number | null;
  file_size_bytes: number | null;
  error_message: string | null;
  background_image_path: string | null;
  output_format: 'audio_only' | 'audio_image' | 'audio_video';
  cover_image_path: string | null;
  chapters: Array<{
    title: string;
    text: string;
    start_seconds?: number | null;
    end_seconds?: number | null;
    duration_seconds?: number | null;
    music_mood?: string | null;
    music_path?: string | null;
    image_path?: string | null;
    visual_prompt?: string | null;
    audio_path?: string | null;
  }> | null;
  voice_casting: Record<string, string> | null;
  music_enabled: boolean;
  music_mood: string | null;
  music_volume_db: number;
  speed: number;
  pitch: number;
  mp3_path: string | null;
  video_orientation: 'landscape' | 'vertical';
  caption_style_preset: string | null;
  image_generation_enabled: boolean;
  youtube_channel_id: string | null;
  // Per-track mix offsets persisted on the audiobook. v0.24.0 only
  // uses the top-level keys; the editor (v0.25.0) hangs per-clip
  // overrides under ``clips``.
  track_mix?: {
    voice_db?: number;
    music_db?: number;
    sfx_db?: number;
    voice_mute?: boolean;
    music_mute?: boolean;
    sfx_mute?: boolean;
    clips?: Record<string, { gain_db?: number; mute?: boolean }>;
  } | null;
  created_at: string;
  updated_at: string;
}

export interface AudiobookCreate {
  title: string;
  text: string;
  voice_profile_id: string;
  output_format?: 'audio_only' | 'audio_image' | 'audio_video';
  cover_image_path?: string | null;
  voice_casting?: Record<string, string> | null;
  music_enabled?: boolean;
  music_mood?: string | null;
  music_volume_db?: number;
  speed?: number;
  pitch?: number;
  video_orientation?: 'landscape' | 'vertical';
  caption_style_preset?: string | null;
  image_generation_enabled?: boolean;
  per_chapter_music?: boolean;
  chapter_moods?: string[] | null;
}

// ---------------------------------------------------------------------------
// YouTube
// ---------------------------------------------------------------------------

export interface YouTubeChannel {
  id: string;
  channel_id: string;
  channel_name: string;
  is_active: boolean;
  upload_days: string[] | null;
  upload_time: string | null;
}

export interface YouTubeUpload {
  id: string;
  episode_id: string;
  channel_id: string;
  youtube_video_id: string | null;
  youtube_url: string | null;
  title: string;
  privacy_status: string;
  upload_status: 'pending' | 'uploading' | 'done' | 'failed';
  error_message: string | null;
  created_at: string;
}

export interface YouTubeUploadRequest {
  title: string;
  description: string;
  tags: string[];
  privacy_status: 'public' | 'unlisted' | 'private';
}

// ── YouTube Playlists + Analytics ─────────────────────────────────────────

export interface YouTubePlaylist {
  id: string;
  channel_id: string;
  youtube_playlist_id: string;
  title: string;
  description: string | null;
  privacy_status: string;
  item_count: number;
  created_at: string;
}

export interface YouTubeVideoStats {
  video_id: string;
  title: string;
  views: number;
  likes: number;
  comments: number;
  published_at: string | null;
}

// ── Character Packs ──────────────────────────────────────────────────────

export interface CharacterPack {
  id: string;
  name: string;
  description: string | null;
  thumbnail_asset_id: string | null;
  character_lock: Record<string, unknown> | null;
  style_lock: Record<string, unknown> | null;
  created_at: string;
}

export interface CharacterPackCreate {
  name: string;
  description?: string | null;
  thumbnail_asset_id?: string | null;
  character_lock?: Record<string, unknown> | null;
  style_lock?: Record<string, unknown> | null;
}

// ── Video editing ────────────────────────────────────────────────────────

export interface BorderConfig {
  width: number;
  color: string;
  style: 'solid' | 'rounded' | 'glow';
}

