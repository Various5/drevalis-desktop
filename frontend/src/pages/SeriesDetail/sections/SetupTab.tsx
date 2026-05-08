import { useState } from 'react';
import {
  ChevronDown,
  ChevronRight,
  Film,
  Monitor,
  Music,
  Music2,
  Palette,
  Settings2,
  Smartphone,
  Subtitles,
  Video,
  Youtube,
} from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Select } from '@/components/ui/Select';
import { Input, Textarea } from '@/components/ui/Input';
import {
  CaptionStyleEditor,
} from '@/components/captions/CaptionStyleEditor';
import { VisualStylePresetPopover } from './VisualStylePresetPopover';
import { AssetLockPicker } from './AssetLockPicker';
import type { CaptionStyle, ComfyUIWorkflow } from '@/types';

// ---------------------------------------------------------------------------
// CollapsibleSection — local to this file; mirrors the pattern from _monolith.
// ---------------------------------------------------------------------------

function CollapsibleSection({
  title,
  icon: Icon,
  defaultOpen = false,
  children,
}: {
  title: string;
  icon: React.ElementType;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <Card padding="none">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between gap-3 px-5 py-3.5 text-left hover:bg-bg-hover transition-colors duration-fast"
      >
        <div className="flex items-center gap-2.5">
          <Icon size={16} className="text-accent shrink-0" />
          <span className="text-md font-semibold text-txt-primary">{title}</span>
        </div>
        {open ? (
          <ChevronDown size={16} className="text-txt-tertiary" />
        ) : (
          <ChevronRight size={16} className="text-txt-tertiary" />
        )}
      </button>
      {open && (
        <div className="px-5 pb-5 pt-1 border-t border-border">{children}</div>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Language options
// ---------------------------------------------------------------------------

const LANGUAGE_OPTIONS = [
  { value: 'en-US', label: 'English (US)' },
  { value: 'en-GB', label: 'English (UK)' },
  { value: 'en-AU', label: 'English (Australia)' },
  { value: 'de-DE', label: 'German (Germany)' },
  { value: 'de-AT', label: 'German (Austria)' },
  { value: 'de-CH', label: 'German (Switzerland)' },
  { value: 'fr-FR', label: 'French (France)' },
  { value: 'es-ES', label: 'Spanish (Spain)' },
  { value: 'es-MX', label: 'Spanish (Mexico)' },
  { value: 'pt-BR', label: 'Portuguese (Brazil)' },
  { value: 'pt-PT', label: 'Portuguese (Portugal)' },
  { value: 'it-IT', label: 'Italian' },
  { value: 'nl-NL', label: 'Dutch' },
  { value: 'pl-PL', label: 'Polish' },
  { value: 'sv-SE', label: 'Swedish' },
  { value: 'da-DK', label: 'Danish' },
  { value: 'no-NO', label: 'Norwegian' },
  { value: 'fi-FI', label: 'Finnish' },
  { value: 'ru-RU', label: 'Russian' },
  { value: 'tr-TR', label: 'Turkish' },
  { value: 'ar-SA', label: 'Arabic (Saudi)' },
  { value: 'hi-IN', label: 'Hindi' },
  { value: 'ja-JP', label: 'Japanese' },
  { value: 'ko-KR', label: 'Korean' },
  { value: 'zh-CN', label: 'Chinese (Mandarin, Simplified)' },
  { value: 'zh-TW', label: 'Chinese (Traditional)' },
];

// ---------------------------------------------------------------------------
// Visual style presets
// ---------------------------------------------------------------------------

const VISUAL_STYLE_PRESETS = [
  {
    label: 'Cinematic',
    value:
      'Cinematic film style, dramatic lighting, shallow depth of field, professional color grading, anamorphic lens flare, 8k resolution',
  },
  {
    label: 'Space / Sci-Fi',
    value:
      'Deep space photography, nebulas, galaxies, planets with atmospheric rings, cosmic dust, NASA-style imagery, dark void background, volumetric lighting',
  },
  {
    label: 'Nature / Landscape',
    value:
      'Epic landscape photography, golden hour lighting, dramatic clouds, lush vegetation, aerial drone shots, National Geographic style, natural colors',
  },
  {
    label: 'Urban / City',
    value:
      'Urban cityscape, neon lights, moody atmosphere, rain-slicked streets, architectural photography, cyberpunk aesthetic, night city skyline',
  },
  {
    label: 'Abstract / Fractal',
    value:
      'Abstract digital art, fractal geometry, flowing colors, mathematical patterns, generative art, vibrant gradients, psychedelic visuals',
  },
  {
    label: 'Macro / Detail',
    value:
      'Extreme macro photography, intricate details, shallow depth of field, crystal-clear focus, natural textures, dewdrops and surfaces',
  },
  {
    label: 'Documentary',
    value:
      'Documentary photography style, photojournalistic, natural lighting, candid moments, authentic atmosphere, true-to-life colors',
  },
  {
    label: 'Dark / Horror',
    value:
      'Dark gothic atmosphere, deep shadows, eerie fog, abandoned locations, desaturated colors, horror movie aesthetic, suspenseful mood',
  },
  {
    label: 'Fantasy / Mythical',
    value:
      'Epic fantasy art, mythical creatures, enchanted forests, magical lighting, otherworldly landscapes, high fantasy illustration style',
  },
  {
    label: 'Anime / Illustration',
    value:
      'Anime art style, vibrant colors, clean line art, dynamic composition, Studio Ghibli inspired backgrounds, cel-shaded aesthetics',
  },
] as const;

// ---------------------------------------------------------------------------
// Music mood options
// ---------------------------------------------------------------------------

const MUSIC_MOODS = [
  { value: 'upbeat', label: 'Upbeat' },
  { value: 'dramatic', label: 'Dramatic' },
  { value: 'calm', label: 'Calm' },
  { value: 'energetic', label: 'Energetic' },
  { value: 'mysterious', label: 'Mysterious' },
  { value: 'playful', label: 'Playful' },
];

// ---------------------------------------------------------------------------
// SetupTab props
// ---------------------------------------------------------------------------

export interface SetupTabProps {
  // Voice & language
  editDuration: string;
  onDurationChange: (v: string) => void;
  editLanguage: string;
  onLanguageChange: (v: string) => void;
  editCharacter: string;
  onCharacterChange: (v: string) => void;
  editCaptionStyle: CaptionStyle;
  onCaptionStyleChange: (v: CaptionStyle) => void;

  // Visual
  editStyle: string;
  onStyleChange: (v: string) => void;

  // Music
  editMusicEnabled: boolean;
  onMusicEnabledChange: (v: boolean) => void;
  editMusicMood: string;
  onMusicMoodChange: (v: string) => void;
  editMusicVolume: number;
  onMusicVolumeChange: (v: number) => void;

  // Publish
  editYoutubeChannelId: string;
  onYoutubeChannelIdChange: (v: string) => void;
  youtubeChannels: Array<{ id: string; channel_name: string }>;

  // Content format / pipeline
  editContentFormat: 'shorts' | 'longform' | 'music_video';
  onContentFormatChange: (v: 'shorts' | 'longform' | 'music_video') => void;
  editAspectRatio: string;
  onAspectRatioChange: (v: string) => void;
  editTargetMinutes: number;
  onTargetMinutesChange: (v: number) => void;
  editScenesPerChapter: number;
  onScenesPerChapterChange: (v: number) => void;
  editVisualConsistency: string;
  onVisualConsistencyChange: (v: string) => void;
  editSceneMode: 'image' | 'video';
  onSceneModeChange: (v: 'image' | 'video') => void;
  editVideoWorkflowId: string;
  onVideoWorkflowIdChange: (v: string) => void;
  workflows: ComfyUIWorkflow[];

  // Tone profile
  editTonePersona: string;
  onTonePersonaChange: (v: string) => void;
  editToneForbidden: string;
  onToneForbiddenChange: (v: string) => void;
  editToneRequiredMoves: string;
  onToneRequiredMovesChange: (v: string) => void;
  editToneReadingLevel: number;
  onToneReadingLevelChange: (v: number) => void;
  editToneMaxSentence: number;
  onToneMaxSentenceChange: (v: number) => void;
  editToneStyleSample: string;
  onToneStyleSampleChange: (v: string) => void;
  editToneSignaturePhrases: string;
  onToneSignaturePhrasesChange: (v: string) => void;
  editToneAllowListicle: boolean;
  onToneAllowListicleChange: (v: boolean) => void;
  editToneCtaBoilerplate: boolean;
  onToneCtaBoilerplateChange: (v: boolean) => void;

  // Asset locks
  editCharacterAssetIds: string;
  onCharacterAssetIdsChange: (v: string) => void;
  editCharacterStrength: number;
  onCharacterStrengthChange: (v: number) => void;
  editCharacterLora: string;
  onCharacterLoraChange: (v: string) => void;
  editStyleAssetIds: string;
  onStyleAssetIdsChange: (v: string) => void;
  editStyleStrength: number;
  onStyleStrengthChange: (v: number) => void;
  editStyleLora: string;
  onStyleLoraChange: (v: string) => void;
}

// ---------------------------------------------------------------------------
// SetupTab
// ---------------------------------------------------------------------------

export function SetupTab({
  // Voice & language
  editDuration,
  onDurationChange,
  editLanguage,
  onLanguageChange,
  editCharacter,
  onCharacterChange,
  editCaptionStyle,
  onCaptionStyleChange,
  // Visual
  editStyle,
  onStyleChange,
  // Music
  editMusicEnabled,
  onMusicEnabledChange,
  editMusicMood,
  onMusicMoodChange,
  editMusicVolume,
  onMusicVolumeChange,
  // Publish
  editYoutubeChannelId,
  onYoutubeChannelIdChange,
  youtubeChannels,
  // Content format / pipeline
  editContentFormat,
  onContentFormatChange,
  editAspectRatio,
  onAspectRatioChange,
  editTargetMinutes,
  onTargetMinutesChange,
  editScenesPerChapter,
  onScenesPerChapterChange,
  editVisualConsistency,
  onVisualConsistencyChange,
  editSceneMode,
  onSceneModeChange,
  editVideoWorkflowId,
  onVideoWorkflowIdChange,
  workflows,
  // Tone profile
  editTonePersona,
  onTonePersonaChange,
  editToneForbidden,
  onToneForbiddenChange,
  editToneRequiredMoves,
  onToneRequiredMovesChange,
  editToneReadingLevel,
  onToneReadingLevelChange,
  editToneMaxSentence,
  onToneMaxSentenceChange,
  editToneStyleSample,
  onToneStyleSampleChange,
  editToneSignaturePhrases,
  onToneSignaturePhrasesChange,
  editToneAllowListicle,
  onToneAllowListicleChange,
  editToneCtaBoilerplate,
  onToneCtaBoilerplateChange,
  // Asset locks
  editCharacterAssetIds,
  onCharacterAssetIdsChange,
  editCharacterStrength,
  onCharacterStrengthChange,
  editCharacterLora,
  onCharacterLoraChange,
  editStyleAssetIds,
  onStyleAssetIdsChange,
  editStyleStrength,
  onStyleStrengthChange,
  editStyleLora,
  onStyleLoraChange,
}: SetupTabProps) {
  return (
    <div className="space-y-3">
      {/* ── Voice & Language ──────────────────────────────────────────── */}
      <CollapsibleSection title="Voice & Language" icon={Subtitles} defaultOpen={false}>
        <div className="mt-3 space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Select
              label="Target Duration"
              value={editDuration}
              onChange={(e) => onDurationChange(e.target.value)}
              options={[
                { value: '15', label: '15 seconds' },
                { value: '30', label: '30 seconds' },
                { value: '60', label: '60 seconds' },
              ]}
            />
            <Select
              label="Language"
              value={editLanguage}
              onChange={(e) => onLanguageChange(e.target.value)}
              hint="Narration language. Visual prompts stay in English."
              options={LANGUAGE_OPTIONS}
            />
          </div>
          <Input
            label="Character Description"
            value={editCharacter}
            onChange={(e) => onCharacterChange(e.target.value)}
            placeholder="Leave empty for landscape / abstract topics..."
            hint="Only needed when the series features a recurring character"
          />
          <div>
            <p className="text-xs font-medium text-txt-secondary mb-2">Caption Style</p>
            <CaptionStyleEditor value={editCaptionStyle} onChange={onCaptionStyleChange} />
          </div>
        </div>
      </CollapsibleSection>

      {/* ── Visual ───────────────────────────────────────────────────── */}
      <CollapsibleSection title="Visual Style" icon={Palette} defaultOpen={false}>
        <div className="mt-3 space-y-3">
          <VisualStylePresetPopover
            presets={VISUAL_STYLE_PRESETS}
            currentValue={editStyle}
            onPick={onStyleChange}
          />
          <Textarea
            label="Style Prompt"
            value={editStyle}
            onChange={(e) => onStyleChange(e.target.value)}
            placeholder="Describe the visual aesthetic: color palette, lighting, mood, art style..."
            hint="Picking a preset fills this in — you can still tweak the wording freely."
            rows={3}
          />
        </div>
      </CollapsibleSection>

      {/* ── Pipeline ─────────────────────────────────────────────────── */}
      <CollapsibleSection title="Content Format & Pipeline" icon={Settings2} defaultOpen={false}>
        <div className="mt-3 space-y-4">
          {/* 3-way format segmented control */}
          <div>
            <label className="text-xs font-medium text-txt-secondary block mb-2">
              Format
            </label>
            <div className="inline-flex w-full rounded-lg border border-border bg-bg-elevated p-1">
              {(
                [
                  { id: 'shorts', label: 'Shorts', sub: '9:16', aspect: '9:16', icon: Smartphone },
                  { id: 'longform', label: 'Long-form', sub: '16:9', aspect: '16:9', icon: Monitor },
                  { id: 'music_video', label: 'Music', sub: '9:16', aspect: '9:16', icon: Music2 },
                ] as const
              ).map((fmt) => {
                const active = editContentFormat === fmt.id;
                const Icon = fmt.icon;
                return (
                  <button
                    key={fmt.id}
                    type="button"
                    onClick={() => {
                      onContentFormatChange(fmt.id);
                      onAspectRatioChange(fmt.aspect);
                    }}
                    className={[
                      'flex-1 flex items-center justify-center gap-1.5 rounded-md px-3 py-2 text-xs font-medium transition-all duration-fast',
                      active
                        ? 'bg-accent-muted text-accent shadow-sm'
                        : 'text-txt-secondary hover:bg-bg-hover hover:text-txt-primary',
                    ].join(' ')}
                    aria-pressed={active}
                  >
                    <Icon size={13} />
                    <span className="hidden sm:inline">{fmt.label}</span>
                    <span className="text-[10px] text-txt-muted">{fmt.sub}</span>
                  </button>
                );
              })}
            </div>
            {editContentFormat === 'music_video' && (
              <p className="mt-2 text-[11px] text-txt-tertiary">
                Music videos use an AI lyric + song generator (ACE Step / lyric-aware) for the
                backing track, then beat-match scene cuts to the song.
              </p>
            )}
          </div>

          {/* Longform options */}
          <div
            className={[
              'overflow-hidden transition-all duration-slow',
              editContentFormat === 'longform' ? 'max-h-[600px] opacity-100' : 'max-h-0 opacity-0',
            ].join(' ')}
            aria-hidden={editContentFormat !== 'longform'}
          >
            <div className="space-y-4 pt-1">
              <div>
                <label className="text-xs font-medium text-txt-secondary block mb-1">
                  Target Duration
                </label>
                <select
                  value={editTargetMinutes}
                  onChange={(e) => onTargetMinutesChange(Number(e.target.value))}
                  className="w-full bg-bg-elevated border border-border rounded-lg px-3 py-2 text-sm text-txt-primary"
                >
                  {[15, 20, 30, 45, 60, 90, 120].map((m) => (
                    <option key={m} value={m}>{m} minutes</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="text-xs font-medium text-txt-secondary block mb-1">
                  Scenes per Chapter
                </label>
                <select
                  value={editScenesPerChapter}
                  onChange={(e) => onScenesPerChapterChange(Number(e.target.value))}
                  className="w-full bg-bg-elevated border border-border rounded-lg px-3 py-2 text-sm text-txt-primary"
                >
                  {[4, 6, 8, 10, 12, 15].map((n) => (
                    <option key={n} value={n}>{n} scenes</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="text-xs font-medium text-txt-secondary block mb-1">
                  Aspect Ratio
                </label>
                <div className="flex gap-2">
                  {[
                    { value: '16:9', label: '16:9 Landscape' },
                    { value: '9:16', label: '9:16 Portrait' },
                    { value: '1:1', label: '1:1 Square' },
                  ].map((ar) => (
                    <button
                      key={ar.value}
                      type="button"
                      onClick={() => onAspectRatioChange(ar.value)}
                      className={[
                        'flex-1 px-3 py-2 rounded-lg border text-xs font-medium transition-colors duration-fast text-center',
                        editAspectRatio === ar.value
                          ? 'border-accent bg-accent/10 text-accent'
                          : 'border-border bg-bg-elevated text-txt-secondary hover:bg-bg-hover',
                      ].join(' ')}
                    >
                      {ar.label}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="text-xs font-medium text-txt-secondary block mb-1">
                  Visual Consistency Prompt
                </label>
                <textarea
                  value={editVisualConsistency}
                  onChange={(e) => onVisualConsistencyChange(e.target.value)}
                  placeholder="Style prompt appended to every scene for visual consistency (e.g., 'cinematic 4K, warm color grading, anime style')"
                  className="w-full min-h-[60px] px-3 py-2 text-sm bg-bg-elevated border border-border rounded-lg text-txt-primary placeholder:text-txt-tertiary resize-y"
                />
              </div>
            </div>
          </div>

          {/* Scene mode */}
          <div className="pt-2 border-t border-border/50">
            <label className="text-xs font-medium text-txt-secondary block mb-2">
              Scene Generation Mode
            </label>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => onSceneModeChange('image')}
                className={[
                  'flex-1 px-4 py-2.5 rounded-lg border text-sm font-medium transition-colors duration-fast text-center',
                  editSceneMode === 'image'
                    ? 'border-accent bg-accent/10 text-accent'
                    : 'border-border bg-bg-elevated text-txt-secondary hover:bg-bg-hover',
                ].join(' ')}
              >
                Image (Ken Burns)
              </button>
              <button
                type="button"
                onClick={() => onSceneModeChange('video')}
                className={[
                  'flex-1 px-4 py-2.5 rounded-lg border text-sm font-medium transition-colors duration-fast text-center',
                  editSceneMode === 'video'
                    ? 'border-accent bg-accent/10 text-accent'
                    : 'border-border bg-bg-elevated text-txt-secondary hover:bg-bg-hover',
                ].join(' ')}
              >
                Video (Wan 2.6)
              </button>
            </div>
            {editSceneMode === 'image' && (
              <p className="mt-2 text-xs text-txt-tertiary">
                Each scene is a still image. Ken Burns zoom/pan effects with crossfade transitions.
              </p>
            )}
            {editSceneMode === 'video' && (
              <div className="mt-3 space-y-3">
                <Select
                  label="Video Workflow"
                  value={editVideoWorkflowId}
                  onChange={(e) => onVideoWorkflowIdChange(e.target.value)}
                  options={[
                    { value: '', label: 'Select a video workflow...' },
                    ...workflows.map((wf) => ({
                      value: wf.id,
                      label: wf.name + (wf.description ? ` - ${wf.description}` : ''),
                    })),
                  ]}
                  hint="Select a ComfyUI workflow for text-to-video generation (e.g. Wan 2.6)"
                />
                <p className="text-xs text-txt-tertiary">
                  Each scene is generated as a ~5 second video clip. Uses more GPU time than image mode.
                </p>
              </div>
            )}
          </div>
        </div>
      </CollapsibleSection>

      {/* ── Music ────────────────────────────────────────────────────── */}
      <CollapsibleSection title="Background Music" icon={Music} defaultOpen={false}>
        <div className="mt-3 space-y-4">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => onMusicEnabledChange(!editMusicEnabled)}
              className={[
                'relative w-9 h-5 rounded-full transition-colors duration-fast',
                editMusicEnabled ? 'bg-accent' : 'bg-bg-active',
              ].join(' ')}
              role="switch"
              aria-checked={editMusicEnabled}
            >
              <span
                className={[
                  'absolute top-0.5 w-4 h-4 rounded-full bg-white shadow-sm transition-transform duration-fast',
                  editMusicEnabled ? 'translate-x-4' : 'translate-x-0.5',
                ].join(' ')}
              />
            </button>
            <label className="text-sm font-medium text-txt-primary">
              Enable background music
            </label>
          </div>

          {editMusicEnabled && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <Select
                label="Mood"
                value={editMusicMood}
                onChange={(e) => onMusicMoodChange(e.target.value)}
                options={MUSIC_MOODS}
              />
              <div className="flex flex-col gap-1">
                <label className="text-xs font-medium text-txt-secondary">
                  Volume: {editMusicVolume} dB
                </label>
                <div className="flex items-center gap-3 h-8">
                  <input
                    type="range"
                    min={-20}
                    max={-6}
                    step={1}
                    value={editMusicVolume}
                    onChange={(e) => onMusicVolumeChange(Number(e.target.value))}
                    className="w-full accent-accent h-1.5 bg-bg-elevated rounded-full appearance-none cursor-pointer
                      [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3.5 [&::-webkit-slider-thumb]:h-3.5
                      [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-accent [&::-webkit-slider-thumb]:shadow-sm
                      [&::-webkit-slider-thumb]:cursor-pointer [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-bg-base"
                  />
                  <span className="text-xs text-txt-tertiary font-mono w-10 text-right shrink-0">
                    {editMusicVolume} dB
                  </span>
                </div>
                <p className="text-[10px] text-txt-tertiary">
                  Lower values make the music quieter relative to narration
                </p>
              </div>
            </div>
          )}
        </div>
      </CollapsibleSection>

      {/* ── Publish ──────────────────────────────────────────────────── */}
      {youtubeChannels.length > 0 && (
        <CollapsibleSection title="YouTube Channel" icon={Youtube} defaultOpen={false}>
          <div className="mt-3">
            <label className="text-xs font-medium text-txt-secondary block mb-2">
              Upload to Channel
            </label>
            <select
              value={editYoutubeChannelId}
              onChange={(e) => onYoutubeChannelIdChange(e.target.value)}
              className="w-full bg-bg-elevated border border-border rounded-lg px-3 py-2 text-sm text-txt-primary"
            >
              <option value="">No channel assigned</option>
              {youtubeChannels.map((ch) => (
                <option key={ch.id} value={ch.id}>
                  {ch.channel_name}
                </option>
              ))}
            </select>
            <p className="text-[10px] text-txt-tertiary mt-1.5">
              Episodes in this series will upload to the selected channel.
            </p>
          </div>
        </CollapsibleSection>
      )}

      {/* ── Long-form ────────────────────────────────────────────────── */}
      {editContentFormat === 'longform' && (
        <CollapsibleSection title="Long-form Options" icon={Film} defaultOpen={true}>
          <div className="mt-3 space-y-3">
            <div>
              <label className="text-xs font-medium text-txt-secondary block mb-1">
                Aspect Ratio
              </label>
              <div className="flex gap-2">
                {[
                  { value: '16:9', label: '16:9 Landscape' },
                  { value: '9:16', label: '9:16 Portrait' },
                  { value: '1:1', label: '1:1 Square' },
                ].map((ar) => (
                  <button
                    key={ar.value}
                    type="button"
                    onClick={() => onAspectRatioChange(ar.value)}
                    className={[
                      'flex-1 px-3 py-2 rounded-lg border text-xs font-medium transition-colors duration-fast text-center',
                      editAspectRatio === ar.value
                        ? 'border-accent bg-accent/10 text-accent'
                        : 'border-border bg-bg-elevated text-txt-secondary hover:bg-bg-hover',
                    ].join(' ')}
                  >
                    {ar.label}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="text-xs font-medium text-txt-secondary block mb-1">
                Visual Consistency Prompt
              </label>
              <textarea
                value={editVisualConsistency}
                onChange={(e) => onVisualConsistencyChange(e.target.value)}
                placeholder="Style prompt appended to every scene (e.g., 'cinematic 4K, warm color grading')"
                className="w-full min-h-[60px] px-3 py-2 text-sm bg-bg-elevated border border-border rounded-lg text-txt-primary placeholder:text-txt-tertiary resize-y"
              />
            </div>
          </div>
        </CollapsibleSection>
      )}

      {/* ── Tone Profile ─────────────────────────────────────────────── */}
      <CollapsibleSection title="Tone Profile" icon={Settings2} defaultOpen={false}>
        <div className="mt-3 space-y-3">
          <p className="text-[11px] text-txt-muted">
            Steers the script step's voice, banned vocabulary, and sentence-length cap.
            Leave fields blank for the neutral default.
          </p>

          <label className="text-[11px] text-txt-secondary block">
            Persona
            <input
              type="text"
              value={editTonePersona}
              onChange={(e) => onTonePersonaChange(e.target.value)}
              placeholder='e.g. "wry historian", "deadpan explainer"'
              className="w-full px-2 py-1 mt-1 text-xs bg-bg-elevated border border-border rounded text-txt-primary placeholder:text-txt-tertiary"
            />
          </label>

          <label className="text-[11px] text-txt-secondary block">
            Forbidden words (comma-separated)
            <textarea
              value={editToneForbidden}
              onChange={(e) => onToneForbiddenChange(e.target.value)}
              placeholder="e.g. literally, basically, vibes"
              className="w-full min-h-[44px] px-2 py-1 mt-1 text-xs bg-bg-elevated border border-border rounded text-txt-primary placeholder:text-txt-tertiary resize-y"
            />
          </label>

          <label className="text-[11px] text-txt-secondary block">
            Required moves (one per line)
            <textarea
              value={editToneRequiredMoves}
              onChange={(e) => onToneRequiredMovesChange(e.target.value)}
              placeholder={'always cite a primary source\nalways end on a contrarian observation'}
              className="w-full min-h-[60px] px-2 py-1 mt-1 text-xs bg-bg-elevated border border-border rounded text-txt-primary placeholder:text-txt-tertiary resize-y"
            />
          </label>

          <div className="grid grid-cols-2 gap-2">
            <label className="text-[11px] text-txt-secondary">
              Reading level (1-18)
              <input
                type="number"
                min={1}
                max={18}
                value={editToneReadingLevel}
                onChange={(e) => onToneReadingLevelChange(parseInt(e.target.value, 10) || 8)}
                className="w-full px-2 py-1 mt-1 text-xs bg-bg-elevated border border-border rounded text-txt-primary"
              />
            </label>
            <label className="text-[11px] text-txt-secondary">
              Max sentence words
              <input
                type="number"
                min={6}
                max={40}
                value={editToneMaxSentence}
                onChange={(e) => onToneMaxSentenceChange(parseInt(e.target.value, 10) || 18)}
                className="w-full px-2 py-1 mt-1 text-xs bg-bg-elevated border border-border rounded text-txt-primary"
              />
            </label>
          </div>

          <label className="text-[11px] text-txt-secondary block">
            Style sample (~200 words to mimic)
            <textarea
              value={editToneStyleSample}
              onChange={(e) => onToneStyleSampleChange(e.target.value)}
              placeholder="Paste a paragraph in the voice you want the LLM to imitate."
              className="w-full min-h-[80px] px-2 py-1 mt-1 text-xs bg-bg-elevated border border-border rounded text-txt-primary placeholder:text-txt-tertiary resize-y"
            />
          </label>

          <label className="text-[11px] text-txt-secondary block">
            Signature phrases (comma-separated, used sparingly)
            <input
              type="text"
              value={editToneSignaturePhrases}
              onChange={(e) => onToneSignaturePhrasesChange(e.target.value)}
              placeholder='e.g. "the receipts show", "what is actually true is"'
              className="w-full px-2 py-1 mt-1 text-xs bg-bg-elevated border border-border rounded text-txt-primary placeholder:text-txt-tertiary"
            />
          </label>

          <div className="flex gap-4 flex-wrap">
            <label className="flex items-center gap-2 text-[11px] text-txt-secondary cursor-pointer">
              <input
                type="checkbox"
                checked={editToneAllowListicle}
                onChange={(e) => onToneAllowListicleChange(e.target.checked)}
              />
              Allow listicle structure
            </label>
            <label className="flex items-center gap-2 text-[11px] text-txt-secondary cursor-pointer">
              <input
                type="checkbox"
                checked={editToneCtaBoilerplate}
                onChange={(e) => onToneCtaBoilerplateChange(e.target.checked)}
              />
              Allow subscribe / like CTAs in description
            </label>
          </div>
        </div>
      </CollapsibleSection>

      {/* ── Visual Asset Locks ───────────────────────────────────────── */}
      <CollapsibleSection title="Visual Asset Locks" icon={Video} defaultOpen={false}>
        <div className="mt-3 space-y-6">
          {/* Character reference lock */}
          <div>
            <div className="text-xs font-semibold text-txt-primary mb-1">
              Character reference lock
            </div>
            <p className="text-[11px] text-txt-muted mb-2">
              Pin a face or character across scenes. Pick portrait assets from your library —
              workflows with IPAdapter-FaceID slots consume them; others ignore them.
            </p>
            <AssetLockPicker
              ids={editCharacterAssetIds}
              onChange={onCharacterAssetIdsChange}
              title="Pick character reference images"
            />
            <div className="grid grid-cols-2 gap-2 mt-2">
              <label className="text-[11px] text-txt-secondary">
                Strength ({editCharacterStrength.toFixed(2)})
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.05}
                  value={editCharacterStrength}
                  onChange={(e) => onCharacterStrengthChange(parseFloat(e.target.value))}
                  className="w-full"
                />
              </label>
              <label className="text-[11px] text-txt-secondary">
                LoRA (optional)
                <input
                  type="text"
                  value={editCharacterLora}
                  onChange={(e) => onCharacterLoraChange(e.target.value)}
                  placeholder="sdxl_face_v2"
                  className="w-full px-2 py-1 text-xs bg-bg-elevated border border-border rounded text-txt-primary"
                />
              </label>
            </div>
          </div>

          {/* Style reference lock */}
          <div>
            <div className="text-xs font-semibold text-txt-primary mb-1">
              Style reference lock
            </div>
            <p className="text-[11px] text-txt-muted mb-2">
              Pin a look (lighting, palette, film grain). Same picker, separate strength.
            </p>
            <AssetLockPicker
              ids={editStyleAssetIds}
              onChange={onStyleAssetIdsChange}
              title="Pick style reference images"
            />
            <div className="grid grid-cols-2 gap-2 mt-2">
              <label className="text-[11px] text-txt-secondary">
                Strength ({editStyleStrength.toFixed(2)})
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.05}
                  value={editStyleStrength}
                  onChange={(e) => onStyleStrengthChange(parseFloat(e.target.value))}
                  className="w-full"
                />
              </label>
              <label className="text-[11px] text-txt-secondary">
                LoRA (optional)
                <input
                  type="text"
                  value={editStyleLora}
                  onChange={(e) => onStyleLoraChange(e.target.value)}
                  placeholder="sdxl_style_v2"
                  className="w-full px-2 py-1 text-xs bg-bg-elevated border border-border rounded text-txt-primary"
                />
              </label>
            </div>
          </div>
        </div>
      </CollapsibleSection>
    </div>
  );
}
