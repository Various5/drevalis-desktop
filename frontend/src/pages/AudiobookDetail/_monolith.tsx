import { useState, useEffect, useCallback, useRef } from 'react';
import { useToast } from '@/components/ui/Toast';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  Play,
  Pause,
  Download,
  Trash2,
  RefreshCw,
  Save,
  Edit3,
  X,
  Clock,
  Film,
  Type,
  XCircle,
  AlertTriangle,
  Upload,
  Settings,
  Monitor,
  Smartphone,
  Subtitles,
  Image as ImageIcon,
  Sparkles,
} from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { Spinner } from '@/components/ui/Spinner';
import { Dialog, DialogFooter } from '@/components/ui/Dialog';
import { Input, Textarea } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { Breadcrumb } from '@/components/ui/Breadcrumb';
import { audiobooks as audiobooksApi, voiceProfiles as voiceProfilesApi, youtube as youtubeApi } from '@/lib/api';
import { useUnsavedWarning } from '@/hooks/useUnsavedWarning';
import { useDocumentTitle } from '@/hooks/useDocumentTitle';
import type { VoiceProfile } from '@/types';
import type { Audiobook } from '@/types';

// ---------------------------------------------------------------------------
// Polling interval (ms) for regenerating status
// ---------------------------------------------------------------------------

const POLL_INTERVAL = 3000;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDuration(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${String(secs).padStart(2, '0')}`;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function wordCount(text: string): number {
  return text.trim() ? text.trim().split(/\s+/).length : 0;
}

// ---------------------------------------------------------------------------
// Caption style presets
// ---------------------------------------------------------------------------

const CAPTION_PRESETS = [
  { value: null, label: 'No Captions', desc: 'Audio only, no subtitles' },
  { value: 'youtube_highlight', label: 'Highlight', desc: 'Words light up as spoken' },
  { value: 'karaoke', label: 'Karaoke', desc: 'One word at a time with fade' },
  { value: 'tiktok_pop', label: 'TikTok Pop', desc: 'Words pop in with scale effect' },
  { value: 'minimal', label: 'Minimal', desc: 'Small subtle text' },
  { value: 'classic', label: 'Classic', desc: 'Simple white on black outline' },
] as const;

// ---------------------------------------------------------------------------
// Script Renderer -- highlights [Speaker] tags and ## headers
// ---------------------------------------------------------------------------

function ScriptDisplay({ text }: { text: string }) {
  const lines = text.split('\n');

  return (
    <div className="space-y-1 text-sm leading-relaxed">
      {lines.map((line, i) => {
        const trimmed = line.trim();

        // Chapter header
        if (trimmed.startsWith('## ')) {
          return (
            <h3
              key={i}
              className="text-base font-bold text-txt-primary mt-4 mb-2 first:mt-0"
            >
              {trimmed.replace(/^##\s+/, '')}
            </h3>
          );
        }

        // Speaker tag line: [Speaker] text
        const speakerMatch = trimmed.match(/^\[([^\]]+)\]\s*(.*)/);
        if (speakerMatch) {
          return (
            <p key={i} className="text-txt-secondary">
              <span className="font-semibold text-accent">[{speakerMatch[1]}]</span>{' '}
              {speakerMatch[2]}
            </p>
          );
        }

        // Empty line
        if (!trimmed) {
          return <div key={i} className="h-2" />;
        }

        // Regular text
        return (
          <p key={i} className="text-txt-secondary">
            {trimmed}
          </p>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Audiobook Detail Page
// ---------------------------------------------------------------------------

function AudiobookDetail() {
  const { audiobookId } = useParams<{ audiobookId: string }>();
  const navigate = useNavigate();
  const { toast } = useToast();

  const [audiobook, setAudiobook] = useState<Audiobook | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useDocumentTitle(audiobook?.title || 'Audiobook Detail');

  // Audio player state
  const audioRef = useRef<HTMLAudioElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);

  // Editing state
  const [editingChapter, setEditingChapter] = useState<number | null>(null);
  const [editText, setEditText] = useState('');
  const [saving, setSaving] = useState(false);
  const [regeneratingChapter, setRegeneratingChapter] = useState<number | null>(null);
  const [regenerating, setRegenerating] = useState(false);

  // Full text editing
  const [editingFullText, setEditingFullText] = useState(false);
  const [fullEditText, setFullEditText] = useState('');
  const [savingFullText, setSavingFullText] = useState(false);

  // Delete dialog
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [musicPreviewLoading, setMusicPreviewLoading] = useState(false);
  const [musicPreviewUrl, setMusicPreviewUrl] = useState<string | null>(null);
  // Cache-bust query string so the <audio> element actually re-fetches
  // a freshly-rendered preview that lives at the same URL.
  const [musicPreviewBust, setMusicPreviewBust] = useState(0);

  // Mix Controls (v0.24.0). Local slider state mirrors the
  // ``track_mix`` JSONB field on the audiobook record. Saved on
  // Remix click via ``audiobooksApi.remix``.
  type MixState = {
    voice_db: number;
    music_db: number;
    sfx_db: number;
    voice_mute: boolean;
    music_mute: boolean;
    sfx_mute: boolean;
  };
  const [mixState, setMixState] = useState<MixState>({
    voice_db: 0,
    music_db: 0,
    sfx_db: 0,
    voice_mute: false,
    music_mute: false,
    sfx_mute: false,
  });
  const [remixing, setRemixing] = useState(false);

  // Voice editing
  const [voiceDialogOpen, setVoiceDialogOpen] = useState(false);
  const [voiceProfiles, setVoiceProfiles] = useState<VoiceProfile[]>([]);
  const [voiceCasting, setVoiceCasting] = useState<Record<string, string>>({});
  const [savingVoices, setSavingVoices] = useState(false);

  // YouTube upload state
  const [youtubeConnected, setYoutubeConnected] = useState(false);
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [ytTitle, setYtTitle] = useState('');
  const [ytDescription, setYtDescription] = useState('');
  const [ytTags, setYtTags] = useState('');
  const [ytPrivacy, setYtPrivacy] = useState('private');

  // Settings editing state
  const [settingsDialogOpen, setSettingsDialogOpen] = useState(false);
  const [settingsOutputFormat, setSettingsOutputFormat] = useState('audio_only');
  const [settingsMusicEnabled, setSettingsMusicEnabled] = useState(false);
  const [settingsMusicMood, setSettingsMusicMood] = useState('');
  const [settingsSpeed, setSettingsSpeed] = useState(1.0);
  const [settingsPitch, setSettingsPitch] = useState(1.0);
  const [settingsVideoOrientation, setSettingsVideoOrientation] = useState<'landscape' | 'vertical'>('vertical');
  const [settingsCaptionStyle, setSettingsCaptionStyle] = useState<string | null>('youtube_highlight');
  const [savingSettings, setSavingSettings] = useState(false);

  // Detect characters from audiobook text
  const detectedCharacters = audiobook?.text
    ? [...new Set((audiobook.text.match(/^\[([^\]]+)\]/gm) || []).map(m => m.slice(1, -1).trim()))]
    : [];

  // Load voice profiles
  useEffect(() => {
    voiceProfilesApi.list().then(setVoiceProfiles).catch((err: unknown) => {
      toast.error('Failed to load voice profiles', { description: String(err) });
    });
  }, [toast]);

  // Check YouTube connection status
  useEffect(() => {
    youtubeApi
      .getStatus()
      .then((res) => setYoutubeConnected(res.connected))
      .catch(() => setYoutubeConnected(false));
  }, []);

  // Pre-fill YouTube upload dialog from audiobook data
  useEffect(() => {
    if (uploadDialogOpen && audiobook) {
      setYtTitle(audiobook.title || '');
      // Build description from chapters
      const chapterList = (audiobook.chapters ?? [])
        .map((ch: { title: string }, i: number) => `${i + 1}. ${ch.title}`)
        .join('\n');
      setYtDescription(chapterList ? `Chapters:\n${chapterList}` : '');
      setYtTags('');
      setYtPrivacy('private');
    }
  }, [uploadDialogOpen, audiobook]);

  // Pre-fill settings dialog
  useEffect(() => {
    if (settingsDialogOpen && audiobook) {
      setSettingsOutputFormat(audiobook.output_format || 'audio_only');
      setSettingsMusicEnabled(audiobook.music_enabled || false);
      setSettingsMusicMood(audiobook.music_mood || '');
      setSettingsSpeed(audiobook.speed || 1.0);
      setSettingsPitch(audiobook.pitch || 1.0);
      setSettingsVideoOrientation(audiobook.video_orientation || 'vertical');
      setSettingsCaptionStyle(audiobook.caption_style_preset ?? 'youtube_highlight');
    }
  }, [settingsDialogOpen, audiobook]);

  // Seed Mix Controls sliders from the persisted track_mix.
  useEffect(() => {
    if (!audiobook) return;
    const tm = audiobook.track_mix || {};
    setMixState({
      voice_db: tm.voice_db ?? 0,
      music_db: tm.music_db ?? 0,
      sfx_db: tm.sfx_db ?? 0,
      voice_mute: tm.voice_mute ?? false,
      music_mute: tm.music_mute ?? false,
      sfx_mute: tm.sfx_mute ?? false,
    });
  }, [audiobook?.id, audiobook?.track_mix]);

  // Init voice casting from audiobook data when dialog opens.
  // Reconcile casting keys (may use full character names like "Aldric the Undying")
  // with detected characters from text tags (short names like "Aldric").
  useEffect(() => {
    if (voiceDialogOpen && audiobook) {
      const raw = audiobook.voice_casting || {};
      const reconciled: Record<string, string> = {};

      for (const char of detectedCharacters) {
        // Exact match first
        if (raw[char]) {
          reconciled[char] = raw[char];
          continue;
        }
        // Fuzzy: find a casting key that starts with or contains the detected name
        const charLower = char.toLowerCase();
        const match = Object.entries(raw).find(([key]) => {
          const keyLower = key.toLowerCase();
          return (
            keyLower.startsWith(charLower) ||
            charLower.startsWith(keyLower) ||
            keyLower.includes(charLower) ||
            charLower.includes(keyLower)
          );
        });
        if (match) {
          reconciled[char] = match[1];
        }
      }

      setVoiceCasting(reconciled);
    }
  }, [voiceDialogOpen, audiobook, detectedCharacters]);

  const handleSaveVoices = async (regenerate: boolean) => {
    if (!audiobook) return;
    setSavingVoices(true);
    try {
      await audiobooksApi.updateVoices(audiobook.id, {
        voice_casting: voiceCasting,
        voice_profile_id: Object.values(voiceCasting)[0] || undefined,
        regenerate,
      });
      setVoiceDialogOpen(false);
      toast.success('Voice casting saved', { description: regenerate ? 'Regeneration started.' : undefined });
      void fetchAudiobook();
    } catch (err) {
      toast.error('Failed to save voice casting', { description: String(err) });
    } finally { setSavingVoices(false); }
  };

  // Polling
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Unsaved changes warning
  const hasUnsaved = editingChapter !== null || editingFullText;
  useUnsavedWarning(hasUnsaved);

  // ── Fetch audiobook ───────────────────────────────────────────────

  const fetchAudiobook = useCallback(async () => {
    if (!audiobookId) return null;
    try {
      const res = await audiobooksApi.get(audiobookId);
      setAudiobook(res);
      setError(null);
      return res;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load audiobook');
      return null;
    }
  }, [audiobookId]);

  useEffect(() => {
    fetchAudiobook().finally(() => setLoading(false));
  }, [fetchAudiobook]);

  // ── Polling while generating ──────────────────────────────────────

  const startPolling = useCallback(() => {
    if (pollingRef.current) return;
    pollingRef.current = setInterval(async () => {
      const ab = await fetchAudiobook();
      if (ab && ab.status !== 'generating') {
        if (pollingRef.current) {
          clearInterval(pollingRef.current);
          pollingRef.current = null;
        }
      }
    }, POLL_INTERVAL);
  }, [fetchAudiobook]);

  useEffect(() => {
    if (audiobook?.status === 'generating') {
      startPolling();
    }
    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
    };
  }, [audiobook?.status, startPolling]);

  // ── Audio player handlers ─────────────────────────────────────────

  const togglePlay = () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (audio.paused) {
      audio.play().catch(() => {});
      setIsPlaying(true);
    } else {
      audio.pause();
      setIsPlaying(false);
    }
  };

  const seekTo = (seconds: number) => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.currentTime = seconds;
    setCurrentTime(seconds);
  };

  const handleTimeUpdate = () => {
    if (audioRef.current) {
      setCurrentTime(audioRef.current.currentTime);
    }
  };

  const handleLoadedMetadata = () => {
    if (audioRef.current) {
      setDuration(audioRef.current.duration);
    }
  };

  const handleEnded = () => {
    setIsPlaying(false);
    setCurrentTime(0);
  };

  const handleSeekBar = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = parseFloat(e.target.value);
    seekTo(val);
  };

  // ── Chapter editing ───────────────────────────────────────────────

  const startEditChapter = (index: number) => {
    if (!audiobook?.chapters?.[index]) return;
    setEditingChapter(index);
    setEditText(audiobook.chapters[index].text);
  };

  const cancelEditChapter = () => {
    setEditingChapter(null);
    setEditText('');
  };

  const saveChapterText = async () => {
    if (editingChapter === null || !audiobookId) return;
    setSaving(true);
    try {
      // Update the full text via the text endpoint by reconstructing
      // We regenerate the chapter with new text
      await audiobooksApi.regenerateChapter(audiobookId, editingChapter, editText);
      setEditingChapter(null);
      setEditText('');
      toast.success('Chapter saved', { description: 'Chapter regeneration started.' });
      // Refresh to get updated status
      const ab = await fetchAudiobook();
      if (ab?.status === 'generating') {
        startPolling();
      }
    } catch (err) {
      toast.error('Failed to save chapter', { description: String(err) });
    } finally {
      setSaving(false);
    }
  };

  const regenerateChapter = async (index: number) => {
    if (!audiobookId) return;
    setRegeneratingChapter(index);
    try {
      await audiobooksApi.regenerateChapter(audiobookId, index);
      toast.success('Chapter regeneration started');
      const ab = await fetchAudiobook();
      if (ab?.status === 'generating') {
        startPolling();
      }
    } catch (err) {
      toast.error('Failed to regenerate chapter', { description: String(err) });
    } finally {
      setRegeneratingChapter(null);
    }
  };

  // ── Full regeneration ─────────────────────────────────────────────

  const handleRegenerate = async () => {
    if (!audiobookId) return;
    setRegenerating(true);
    try {
      await audiobooksApi.regenerate(audiobookId);
      toast.success('Regeneration started');
      const ab = await fetchAudiobook();
      if (ab?.status === 'generating') {
        startPolling();
      }
    } catch (err) {
      toast.error('Failed to start regeneration', { description: String(err) });
    } finally {
      setRegenerating(false);
    }
  };

  // ── Music preview ─────────────────────────────────────────────────
  // Renders a 30s mix on the server (curated library + AceStep
  // fallback) and surfaces it inline so the user can sanity-check
  // mood + ducking before committing to a full generation.
  const handleMusicPreview = async () => {
    if (!audiobookId || !settingsMusicMood) return;
    setMusicPreviewLoading(true);
    try {
      const r = await audiobooksApi.musicPreview(audiobookId, settingsMusicMood);
      setMusicPreviewUrl(r.url);
      setMusicPreviewBust(Date.now());
      toast.success('Music preview ready');
    } catch (err) {
      toast.error('Music preview failed', { description: String(err) });
    } finally {
      setMusicPreviewLoading(false);
    }
  };

  // ── Remix (apply Mix Controls without re-running TTS) ──────────────
  const handleRemix = async () => {
    if (!audiobookId) return;
    setRemixing(true);
    try {
      await audiobooksApi.remix(audiobookId, mixState);
      toast.success('Remix queued', {
        description: 'Reusing cached audio — should complete in seconds.',
      });
      // Status flips to ``generating`` server-side; the existing
      // polling loop picks it up automatically.
      void fetchAudiobook();
    } catch (err) {
      toast.error('Failed to enqueue remix', { description: String(err) });
    } finally {
      setRemixing(false);
    }
  };

  // ── Cancel in-progress generation ──────────────────────────────────
  // Sets a Redis flag the worker polls between major steps. Actual
  // stop lands at the next boundary (typically <30s during TTS,
  // sub-second outside it). Optimistic toast — actual status flip to
  // ``failed`` with "Cancelled by user" comes via the polling loop.
  const handleCancelGeneration = async () => {
    if (!audiobookId) return;
    setCancelling(true);
    try {
      await audiobooksApi.cancel(audiobookId);
      toast.success('Cancel signal sent', {
        description: 'The job will stop at the next step boundary.',
      });
      void fetchAudiobook();
    } catch (err) {
      toast.error('Failed to cancel', { description: String(err) });
    } finally {
      setCancelling(false);
    }
  };

  // ── Full text editing ─────────────────────────────────────────────

  const startEditFullText = () => {
    if (!audiobook) return;
    setEditingFullText(true);
    setFullEditText(audiobook.text);
  };

  const cancelEditFullText = () => {
    setEditingFullText(false);
    setFullEditText('');
  };

  const saveFullText = async () => {
    if (!audiobookId) return;
    setSavingFullText(true);
    try {
      await audiobooksApi.updateText(audiobookId, fullEditText);
      setEditingFullText(false);
      setFullEditText('');
      toast.success('Script text saved');
      await fetchAudiobook();
    } catch (err) {
      toast.error('Failed to save script text', { description: String(err) });
    } finally {
      setSavingFullText(false);
    }
  };

  // ── Delete ────────────────────────────────────────────────────────

  const handleDelete = async () => {
    if (!audiobookId) return;
    setDeleting(true);
    try {
      await audiobooksApi.delete(audiobookId);
      navigate('/audiobooks');
    } catch (err) {
      toast.error('Failed to delete audiobook', { description: String(err) });
    } finally {
      setDeleting(false);
    }
  };

  // ── YouTube upload ──────────────────────────────────────────────

  const handleYouTubeUpload = async () => {
    if (!audiobookId) return;
    setUploading(true);
    try {
      await audiobooksApi.uploadToYouTube(audiobookId, {
        title: ytTitle,
        description: ytDescription,
        tags: ytTags
          .split(',')
          .map((t) => t.trim())
          .filter(Boolean),
        privacy_status: ytPrivacy,
      });
      setUploadDialogOpen(false);
      toast.success('YouTube upload started', { description: ytTitle });
    } catch (err) {
      toast.error('Failed to start YouTube upload', { description: String(err) });
    } finally {
      setUploading(false);
    }
  };

  // ── Settings save & regenerate ─────────────────────────────────

  const handleSaveSettings = async () => {
    if (!audiobookId) return;
    setSavingSettings(true);
    try {
      await audiobooksApi.updateSettings(audiobookId, {
        output_format: settingsOutputFormat,
        music_enabled: settingsMusicEnabled,
        music_mood: settingsMusicMood || undefined,
        speed: settingsSpeed,
        pitch: settingsPitch,
        video_orientation: settingsOutputFormat !== 'audio_only' ? settingsVideoOrientation : undefined,
        caption_style_preset: settingsOutputFormat !== 'audio_only' ? settingsCaptionStyle : undefined,
      });
      setSettingsDialogOpen(false);
      // Trigger regeneration with new settings
      await audiobooksApi.regenerate(audiobookId);
      toast.success('Settings saved', { description: 'Regeneration started with new settings.' });
      const ab = await fetchAudiobook();
      if (ab?.status === 'generating') {
        startPolling();
      }
    } catch (err) {
      toast.error('Failed to save settings', { description: String(err) });
    } finally {
      setSavingSettings(false);
    }
  };

  // ── Loading / error states ────────────────────────────────────────

  if (loading) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <Spinner size="lg" />
      </div>
    );
  }

  if (error || !audiobook) {
    return (
      <div className="flex flex-col items-center justify-center h-[60vh] gap-4">
        <AlertTriangle size={48} className="text-error opacity-50" />
        <p className="text-txt-secondary">{error || 'Audiobook not found'}</p>
        <Button variant="ghost" onClick={() => navigate('/audiobooks')}>
          <ArrowLeft size={14} />
          Back to Audiobooks
        </Button>
      </div>
    );
  }

  const chapters = audiobook.chapters ?? [];
  const words = wordCount(audiobook.text);
  const isGenerating = audiobook.status === 'generating';
  const isDone = audiobook.status === 'done';

  // ── Render ────────────────────────────────────────────────────────

  return (
    <div>
      {/* Header */}
      <div className="mb-6">
        <Breadcrumb
          items={[
            { label: 'Text to Voice', to: '/audiobooks' },
            { label: audiobook.title || 'Audiobook' },
          ]}
          className="mb-4"
        />

        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-2xl font-bold text-txt-primary">{audiobook.title}</h2>
            <div className="flex items-center gap-3 mt-2">
              <Badge
                variant={
                  isDone ? 'success' :
                  isGenerating ? 'accent' :
                  audiobook.status === 'failed' ? 'error' :
                  'neutral'
                }
                dot
              >
                {audiobook.status}
              </Badge>
              {audiobook.duration_seconds != null && (
                <span className="flex items-center gap-1 text-sm text-txt-secondary">
                  <Clock size={12} />
                  {formatDuration(audiobook.duration_seconds)}
                </span>
              )}
              <span className="flex items-center gap-1 text-sm text-txt-secondary">
                <Type size={12} />
                {words.toLocaleString()} words
              </span>
              {audiobook.file_size_bytes != null && (
                <span className="text-sm text-txt-secondary">
                  {formatFileSize(audiobook.file_size_bytes)}
                </span>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2">
            {isDone && (
              <Button
                variant="primary"
                size="sm"
                onClick={() => navigate(`/audiobooks/${audiobook.id}/edit`)}
                title="Open the multi-track audiobook editor"
              >
                <Edit3 size={14} />
                Edit
              </Button>
            )}
            <Button
              variant="secondary"
              size="sm"
              onClick={startEditFullText}
              disabled={isGenerating || editingFullText}
            >
              <Edit3 size={14} />
              Edit Text
            </Button>
            {detectedCharacters.length > 0 && (
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setVoiceDialogOpen(true)}
                disabled={isGenerating}
              >
                <Edit3 size={14} />
                Change Voices
              </Button>
            )}
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setSettingsDialogOpen(true)}
              disabled={isGenerating}
            >
              <Settings size={14} />
              Settings
            </Button>
            {youtubeConnected && isDone && audiobook.video_path && (
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setUploadDialogOpen(true)}
              >
                <Upload size={14} />
                YouTube
              </Button>
            )}
            <Button
              variant="secondary"
              size="sm"
              loading={regenerating}
              onClick={() => void handleRegenerate()}
              disabled={isGenerating}
            >
              <RefreshCw size={14} />
              Re-generate
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setDeleteDialogOpen(true)}
              className="text-error hover:bg-error-muted"
            >
              <Trash2 size={14} />
            </Button>
          </div>
        </div>
      </div>

      {/* Generating indicator + Cancel button */}
      {isGenerating && (
        <Card padding="md" className="mb-6 border-accent/30">
          <div className="flex items-center gap-3">
            <Spinner size="sm" />
            <span className="text-sm text-txt-secondary flex-1">
              Generating audio... This page will refresh automatically when done.
            </span>
            <Button
              variant="ghost"
              size="sm"
              loading={cancelling}
              onClick={() => void handleCancelGeneration()}
              className="text-error hover:bg-error-muted"
              title="Stop the generation at the next step boundary"
              aria-label="Cancel audiobook generation"
            >
              <XCircle size={14} />
              Cancel
            </Button>
          </div>
        </Card>
      )}

      {/* Error display */}
      {audiobook.status === 'failed' && audiobook.error_message && (
        <Card padding="md" className="mb-6 border-error/30">
          <div className="flex items-start gap-2">
            <XCircle size={16} className="text-error shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-error">Generation failed</p>
              <p className="text-xs text-txt-secondary mt-1">{audiobook.error_message}</p>
            </div>
          </div>
        </Card>
      )}

      {/* Main content: two-column layout */}
      <div className="grid grid-cols-12 gap-6">
        {/* Left column: Audio Player + Chapters + Downloads */}
        <div className="col-span-5 space-y-4">
          {/* Audio Player */}
          {isDone && audiobook.audio_path && (
            <Card padding="md">
              <h3 className="text-sm font-semibold text-txt-primary mb-3">Audio Player</h3>
              <audio
                ref={audioRef}
                src={`/storage/${audiobook.audio_path}`}
                preload="metadata"
                onTimeUpdate={handleTimeUpdate}
                onLoadedMetadata={handleLoadedMetadata}
                onEnded={handleEnded}
                onPause={() => setIsPlaying(false)}
                onPlay={() => setIsPlaying(true)}
              />

              {/* Play button + seek bar */}
              <div className="flex items-center gap-3">
                <button
                  onClick={togglePlay}
                  className="w-10 h-10 rounded-full bg-accent text-txt-onAccent flex items-center justify-center hover:bg-accent-hover transition-colors duration-fast shrink-0"
                >
                  {isPlaying ? <Pause size={16} /> : <Play size={16} className="ml-0.5" />}
                </button>
                <div className="flex-1">
                  <input
                    type="range"
                    min={0}
                    max={duration || 0}
                    step={0.1}
                    value={currentTime}
                    onChange={handleSeekBar}
                    className="w-full h-1.5 rounded-full accent-accent cursor-pointer"
                  />
                  <div className="flex justify-between text-[10px] text-txt-tertiary mt-1">
                    <span>{formatDuration(currentTime)}</span>
                    <span>{formatDuration(duration)}</span>
                  </div>
                </div>
              </div>
            </Card>
          )}

          {/* Chapter image gallery (v0.21.0) */}
          {chapters.length > 0 && audiobook && (
            <ChapterImageGallery
              audiobookId={audiobook.id}
              chapters={chapters}
              onRegenerated={() => void fetchAudiobook()}
            />
          )}

          {/* Chapter list */}
          {chapters.length > 0 && (
            <Card padding="md">
              <h3 className="text-sm font-semibold text-txt-primary mb-3">
                Chapters ({chapters.length})
              </h3>
              <div className="space-y-1">
                {chapters.map((ch, i) => {
                  const hasStartTime = ch.start_seconds != null;
                  return (
                    <div
                      key={i}
                      className={[
                        'flex items-center justify-between px-3 py-2 rounded-md text-sm transition-colors duration-fast',
                        hasStartTime && isDone
                          ? 'cursor-pointer hover:bg-bg-hover'
                          : '',
                      ].join(' ')}
                      onClick={() => {
                        if (hasStartTime && isDone) {
                          seekTo(ch.start_seconds!);
                          if (!isPlaying) togglePlay();
                        }
                      }}
                    >
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="text-xs text-txt-tertiary w-5 shrink-0">
                          {i + 1}.
                        </span>
                        <span className="text-txt-primary truncate">{ch.title}</span>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        {hasStartTime && (
                          <span className="text-xs text-txt-tertiary">
                            {formatDuration(ch.start_seconds!)}
                          </span>
                        )}
                        {!isGenerating && (
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-6 px-1.5"
                            loading={regeneratingChapter === i}
                            onClick={(e) => {
                              e.stopPropagation();
                              void regenerateChapter(i);
                            }}
                          >
                            <RefreshCw size={10} />
                          </Button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </Card>
          )}

          {/* Downloads */}
          {isDone && (
            <Card padding="md">
              <h3 className="text-sm font-semibold text-txt-primary mb-3">Downloads</h3>
              <div className="flex flex-wrap gap-2">
                {audiobook.audio_path && (
                  <a
                    href={`/storage/${audiobook.audio_path}`}
                    download
                    className="flex items-center gap-1.5 px-3 py-2 rounded-md bg-bg-elevated text-sm text-txt-primary hover:bg-bg-hover transition-colors duration-fast"
                  >
                    <Download size={14} className="text-accent" />
                    WAV
                  </a>
                )}
                {audiobook.mp3_path && (
                  <a
                    href={`/storage/${audiobook.mp3_path}`}
                    download
                    className="flex items-center gap-1.5 px-3 py-2 rounded-md bg-bg-elevated text-sm text-txt-primary hover:bg-bg-hover transition-colors duration-fast"
                  >
                    <Download size={14} className="text-accent" />
                    MP3
                  </a>
                )}
                {audiobook.video_path && (
                  <a
                    href={`/storage/${audiobook.video_path}`}
                    download
                    className="flex items-center gap-1.5 px-3 py-2 rounded-md bg-bg-elevated text-sm text-txt-primary hover:bg-bg-hover transition-colors duration-fast"
                  >
                    <Film size={14} className="text-accent" />
                    MP4
                  </a>
                )}
              </div>
            </Card>
          )}

          {/* Mix Controls (v0.24.0) — per-track gain offsets that
              can be remixed without re-running TTS / image gen.
              Sliders are wired live to local state; "Remix" enqueues
              the worker job that re-renders just the audio mix. */}
          {isDone && (
            <Card padding="md">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold text-txt-primary">Mix Controls</h3>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => navigate(`/audiobooks/${audiobook.id}/edit`)}
                  title="Open the multi-track audiobook editor"
                >
                  Open editor
                </Button>
              </div>
              <div className="space-y-3 text-xs">
                {(['voice', 'music', 'sfx'] as const).map((track) => {
                  const dbKey = `${track}_db` as const;
                  const muteKey = `${track}_mute` as const;
                  const value = mixState[dbKey] ?? 0;
                  const muted = mixState[muteKey] ?? false;
                  const labels: Record<typeof track, string> = {
                    voice: 'Voice',
                    music: 'Music',
                    sfx: 'SFX',
                  };
                  return (
                    <div key={track}>
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-txt-secondary">
                          {labels[track]}
                        </span>
                        <span className="tabular-nums text-txt-primary">
                          {muted ? 'muted' : `${value > 0 ? '+' : ''}${value.toFixed(1)} dB`}
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <input
                          type="range"
                          min={-20}
                          max={12}
                          step={0.5}
                          value={value}
                          disabled={muted}
                          onChange={(e) =>
                            setMixState((prev) => ({
                              ...prev,
                              [dbKey]: parseFloat(e.target.value),
                            }))
                          }
                          className="flex-1 accent-accent disabled:opacity-30"
                        />
                        <button
                          type="button"
                          onClick={() =>
                            setMixState((prev) => ({
                              ...prev,
                              [muteKey]: !prev[muteKey],
                            }))
                          }
                          className={[
                            'px-2 py-0.5 rounded text-[10px] uppercase tracking-wide font-medium',
                            muted
                              ? 'bg-error/15 text-error'
                              : 'bg-bg-elevated text-txt-tertiary hover:text-txt-primary',
                          ].join(' ')}
                          title={muted ? 'Unmute' : 'Mute'}
                        >
                          {muted ? 'M' : 'm'}
                        </button>
                      </div>
                    </div>
                  );
                })}
                <div className="pt-2 border-t border-border flex items-center gap-2">
                  <Button
                    variant="primary"
                    size="sm"
                    loading={remixing}
                    onClick={() => void handleRemix()}
                  >
                    Remix
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() =>
                      setMixState({
                        voice_db: 0,
                        music_db: 0,
                        sfx_db: 0,
                        voice_mute: false,
                        music_mute: false,
                        sfx_mute: false,
                      })
                    }
                    title="Reset sliders to passthrough (does not remix)"
                  >
                    Reset
                  </Button>
                  <p className="text-[11px] text-txt-tertiary ml-auto">
                    Reuses cached audio — completes in seconds.
                  </p>
                </div>
              </div>
            </Card>
          )}

          {/* Metadata */}
          <Card padding="md">
            <h3 className="text-sm font-semibold text-txt-primary mb-3">Details</h3>
            <div className="space-y-2 text-xs">
              <div className="flex justify-between">
                <span className="text-txt-tertiary">Output Format</span>
                <span className="text-txt-primary">{audiobook.output_format.replace(/_/g, ' ')}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-txt-tertiary">Speed</span>
                <span className="text-txt-primary">{audiobook.speed}x</span>
              </div>
              <div className="flex justify-between">
                <span className="text-txt-tertiary">Pitch</span>
                <span className="text-txt-primary">{audiobook.pitch}x</span>
              </div>
              {audiobook.music_enabled && (
                <div className="flex justify-between">
                  <span className="text-txt-tertiary">Music</span>
                  <span className="text-txt-primary">{audiobook.music_mood || 'enabled'}</span>
                </div>
              )}
              <div className="flex justify-between">
                <span className="text-txt-tertiary">Created</span>
                <span className="text-txt-primary">
                  {new Date(audiobook.created_at).toLocaleString()}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-txt-tertiary">Updated</span>
                <span className="text-txt-primary">
                  {new Date(audiobook.updated_at).toLocaleString()}
                </span>
              </div>
            </div>
          </Card>
        </div>

        {/* Right column: Script */}
        <div className="col-span-7">
          <Card padding="md" className="sticky top-4">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-semibold text-txt-primary">Script</h3>
              {editingFullText ? (
                <div className="flex items-center gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={cancelEditFullText}
                  >
                    <X size={14} />
                    Cancel
                  </Button>
                  <Button
                    variant="primary"
                    size="sm"
                    loading={savingFullText}
                    onClick={() => void saveFullText()}
                  >
                    <Save size={14} />
                    Save Text
                  </Button>
                </div>
              ) : (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={startEditFullText}
                  disabled={isGenerating}
                >
                  <Edit3 size={14} />
                  Edit
                </Button>
              )}
            </div>

            {editingFullText ? (
              <textarea
                value={fullEditText}
                onChange={(e) => setFullEditText(e.target.value)}
                className="w-full min-h-[600px] font-mono text-xs bg-bg-elevated border border-border rounded-md p-3 text-txt-primary resize-y focus:border-accent focus:shadow-accent-glow transition-all duration-fast"
              />
            ) : (
              <div className="max-h-[calc(100vh-220px)] overflow-y-auto pr-2">
                {chapters.length > 0 ? (
                  <div className="space-y-6">
                    {chapters.map((ch, i) => (
                      <div key={i}>
                        <div className="flex items-center justify-between mb-2">
                          <h4 className="text-sm font-bold text-txt-primary">
                            {ch.title}
                          </h4>
                          {!isGenerating && (
                            <div className="flex items-center gap-1">
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-6 text-[11px]"
                                onClick={() => startEditChapter(i)}
                                disabled={editingChapter !== null}
                              >
                                <Edit3 size={10} />
                                Edit
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-6 text-[11px]"
                                loading={regeneratingChapter === i}
                                onClick={() => void regenerateChapter(i)}
                              >
                                <RefreshCw size={10} />
                                Regen
                              </Button>
                            </div>
                          )}
                        </div>

                        {editingChapter === i ? (
                          <div className="space-y-2">
                            <textarea
                              value={editText}
                              onChange={(e) => setEditText(e.target.value)}
                              className="w-full min-h-[200px] font-mono text-xs bg-bg-elevated border border-accent rounded-md p-3 text-txt-primary resize-y focus:shadow-accent-glow transition-all duration-fast"
                            />
                            <div className="flex items-center gap-2 justify-end">
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={cancelEditChapter}
                              >
                                Cancel
                              </Button>
                              <Button
                                variant="primary"
                                size="sm"
                                loading={saving}
                                onClick={() => void saveChapterText()}
                              >
                                <Save size={12} />
                                Save & Regenerate
                              </Button>
                            </div>
                          </div>
                        ) : (
                          <ScriptDisplay text={ch.text} />
                        )}
                      </div>
                    ))}
                  </div>
                ) : (
                  <ScriptDisplay text={audiobook.text} />
                )}
              </div>
            )}
          </Card>
        </div>
      </div>

      {/* Delete confirmation dialog */}
      <Dialog
        open={deleteDialogOpen}
        onClose={() => setDeleteDialogOpen(false)}
        title="Delete Audiobook"
      >
        <p className="text-sm text-txt-secondary">
          Are you sure you want to delete <strong>{audiobook.title}</strong>?
          This will permanently remove the audiobook and all associated audio files.
        </p>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setDeleteDialogOpen(false)}>
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={deleting}
            onClick={() => void handleDelete()}
            className="bg-error hover:bg-error/80"
          >
            <Trash2 size={14} />
            Delete
          </Button>
        </DialogFooter>
      </Dialog>

      {/* Voice casting dialog */}
      <Dialog
        open={voiceDialogOpen}
        onClose={() => setVoiceDialogOpen(false)}
        title="Change Character Voices"
      >
        <div className="space-y-3">
          <p className="text-sm text-txt-secondary">
            Assign voices to each character, then regenerate the audio.
          </p>
          {detectedCharacters.map(char => {
            const maleVoices = voiceProfiles.filter(v => v.gender === 'male');
            const femaleVoices = voiceProfiles.filter(v => v.gender === 'female');
            const currentVoiceId = voiceCasting[char] || '';
            const currentVoice = voiceProfiles.find(v => v.id === currentVoiceId);
            const currentGender = currentVoice?.gender || 'male';

            return (
              <div key={char} className="p-3 bg-bg-elevated rounded-lg">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-semibold text-txt-primary">[{char}]</span>
                  <div className="flex gap-1">
                    {(['male', 'female'] as const).map(g => (
                      <span key={g} className={`px-2 py-0.5 text-[10px] rounded ${
                        currentGender === g
                          ? g === 'male' ? 'bg-blue-500/20 text-blue-400' : 'bg-pink-500/20 text-pink-400'
                          : 'text-txt-tertiary'
                      }`}>
                        {g === 'male' ? '♂' : '♀'} {g}
                      </span>
                    ))}
                  </div>
                </div>
                <select
                  value={voiceCasting[char] || ''}
                  onChange={(e) => setVoiceCasting(prev => ({ ...prev, [char]: e.target.value }))}
                  className="w-full bg-bg-surface border border-border rounded px-2 py-1.5 text-sm text-txt-primary"
                >
                  <option value="">Select voice...</option>
                  <optgroup label="♂ Male">
                    {maleVoices.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}
                  </optgroup>
                  <optgroup label="♀ Female">
                    {femaleVoices.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}
                  </optgroup>
                </select>
              </div>
            );
          })}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setVoiceDialogOpen(false)}>Cancel</Button>
          <Button variant="secondary" loading={savingVoices} onClick={() => void handleSaveVoices(false)}>
            Save Only
          </Button>
          <Button variant="primary" loading={savingVoices} onClick={() => void handleSaveVoices(true)}>
            <RefreshCw size={14} /> Save & Regenerate
          </Button>
        </DialogFooter>
      </Dialog>

      {/* YouTube Upload Dialog */}
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
            placeholder="audiobook, story, fiction"
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
            loading={uploading}
            onClick={() => void handleYouTubeUpload()}
          >
            <Upload size={14} /> Upload
          </Button>
        </DialogFooter>
      </Dialog>

      {/* Settings Dialog */}
      <Dialog
        open={settingsDialogOpen}
        onClose={() => setSettingsDialogOpen(false)}
        title="Audiobook Settings"
      >
        <div className="space-y-4">
          <Select
            label="Output Format"
            value={settingsOutputFormat}
            onChange={(e) => setSettingsOutputFormat(e.target.value)}
            options={[
              { value: 'audio_only', label: 'Audio Only (WAV + MP3)' },
              { value: 'audio_image', label: 'Audio + Cover Image (MP4)' },
              { value: 'audio_video', label: 'Audio + Video with Waveform (MP4)' },
            ]}
          />

          {/* Orientation Toggle (video outputs only) */}
          {settingsOutputFormat !== 'audio_only' && (
            <div>
              <label className="block text-sm font-medium text-txt-primary mb-2">Orientation</label>
              <div className="flex gap-2">
                {([
                  { value: 'vertical', label: 'Vertical / Shorts', sub: '1080x1920', Icon: Smartphone },
                  { value: 'landscape', label: 'Landscape', sub: '1920x1080', Icon: Monitor },
                ] as const).map(({ value, label, sub, Icon }) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setSettingsVideoOrientation(value)}
                    className={[
                      'flex-1 flex items-center gap-2.5 px-3 py-2.5 rounded-lg border transition text-left',
                      settingsVideoOrientation === value
                        ? 'border-accent bg-accent/10 ring-1 ring-accent/30'
                        : 'border-border hover:border-border-hover bg-bg-elevated',
                    ].join(' ')}
                  >
                    <Icon size={18} className={settingsVideoOrientation === value ? 'text-accent' : 'text-txt-tertiary'} />
                    <div>
                      <div className="text-sm font-medium text-txt-primary">{label}</div>
                      <div className="text-[10px] text-txt-tertiary">{sub}</div>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Caption Style Picker (video outputs only) */}
          {settingsOutputFormat !== 'audio_only' && (
            <div>
              <label className="block text-sm font-medium text-txt-primary mb-2 flex items-center gap-1.5">
                <Subtitles size={14} className="text-txt-tertiary" />
                Caption Style
              </label>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                {CAPTION_PRESETS.map((preset) => (
                  <div
                    key={String(preset.value)}
                    onClick={() => setSettingsCaptionStyle(preset.value)}
                    className={[
                      'p-2.5 rounded-lg border cursor-pointer transition text-center',
                      settingsCaptionStyle === preset.value
                        ? 'border-accent bg-accent/10 ring-1 ring-accent/30'
                        : 'border-border hover:border-border-hover bg-bg-elevated',
                    ].join(' ')}
                  >
                    <div className="text-xs font-medium text-txt-primary">{preset.label}</div>
                    <div className="text-[10px] text-txt-tertiary mt-0.5 leading-tight">{preset.desc}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div>
            <label className="flex items-center gap-2 text-sm text-txt-primary cursor-pointer">
              <input
                type="checkbox"
                checked={settingsMusicEnabled}
                onChange={(e) => setSettingsMusicEnabled(e.target.checked)}
                className="rounded border-border accent-accent"
              />
              Enable background music
            </label>
            {settingsMusicEnabled && (
              <div className="mt-2 space-y-2">
                <Select
                  label="Music Mood"
                  value={settingsMusicMood}
                  onChange={(e) => setSettingsMusicMood(e.target.value)}
                  options={[
                    { value: '', label: 'Select mood...' },
                    { value: 'calm', label: 'Calm' },
                    { value: 'dramatic', label: 'Dramatic' },
                    { value: 'upbeat', label: 'Upbeat' },
                    { value: 'mysterious', label: 'Mysterious' },
                    { value: 'dark', label: 'Dark' },
                    { value: 'romantic', label: 'Romantic' },
                    { value: 'epic', label: 'Epic' },
                  ]}
                />
                {/* Music preview — sanity-check the mix BEFORE
                    committing to a multi-hour generation. */}
                <div className="flex items-center gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={!settingsMusicMood || musicPreviewLoading}
                    loading={musicPreviewLoading}
                    onClick={() => void handleMusicPreview()}
                    title="Render a 30s mix to hear the mood + ducking"
                  >
                    Preview music (30s)
                  </Button>
                  {musicPreviewUrl && (
                    <audio
                      src={`${musicPreviewUrl}?t=${musicPreviewBust}`}
                      controls
                      className="h-8 flex-1"
                    />
                  )}
                </div>
              </div>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-txt-primary mb-1">
              Speed: {settingsSpeed.toFixed(2)}x
            </label>
            <input
              type="range"
              min={0.5}
              max={2.0}
              step={0.05}
              value={settingsSpeed}
              onChange={(e) => setSettingsSpeed(parseFloat(e.target.value))}
              className="w-full h-1.5 rounded-full accent-accent cursor-pointer"
            />
            <div className="flex justify-between text-[10px] text-txt-tertiary mt-1">
              <span>0.5x</span>
              <span>1.0x</span>
              <span>2.0x</span>
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-txt-primary mb-1">
              Pitch: {settingsPitch.toFixed(2)}x
            </label>
            <input
              type="range"
              min={0.5}
              max={2.0}
              step={0.05}
              value={settingsPitch}
              onChange={(e) => setSettingsPitch(parseFloat(e.target.value))}
              className="w-full h-1.5 rounded-full accent-accent cursor-pointer"
            />
            <div className="flex justify-between text-[10px] text-txt-tertiary mt-1">
              <span>0.5x</span>
              <span>1.0x</span>
              <span>2.0x</span>
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => setSettingsDialogOpen(false)}
          >
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={savingSettings}
            onClick={() => void handleSaveSettings()}
          >
            <Save size={14} /> Save Settings & Regenerate
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}

// ─── ChapterImageGallery (v0.21.0) ──────────────────────────────
//
// Visual carousel of the per-chapter AI illustrations. The audiobook
// generator already populates ``chapters[i].image_path``; this
// component just surfaces them with a regenerate-on-click flow that
// hits the new ``/regenerate-chapter-image/{idx}`` endpoint.

interface ChapterRecord {
  index?: number;
  title?: string;
  start_seconds?: number | null;
  end_seconds?: number | null;
  image_path?: string | null;
  visual_prompt?: string | null;
  text?: string | null;
}

function ChapterImageGallery({
  audiobookId,
  chapters,
  onRegenerated,
}: {
  audiobookId: string;
  chapters: ChapterRecord[];
  onRegenerated: () => void;
}) {
  const { toast } = useToast();
  const [openChapter, setOpenChapter] = useState<number | null>(null);
  const [promptOverride, setPromptOverride] = useState('');
  const [regenerating, setRegenerating] = useState(false);

  const chaptersWithImages = chapters.filter(
    (ch) => ch.image_path && ch.image_path.length > 0,
  ).length;

  const handleRegenerate = async (chapterIndex: number) => {
    setRegenerating(true);
    try {
      await audiobooksApi.regenerateChapterImage(
        audiobookId,
        chapterIndex,
        promptOverride.trim() || undefined,
      );
      toast.success('Chapter image regeneration started', {
        description: 'Should swap in within ~30s. Page refreshes when ready.',
      });
      setOpenChapter(null);
      setPromptOverride('');
      // Poll once after 30s — that matches typical Qwen image gen
      // time. The user can also refresh manually.
      setTimeout(() => onRegenerated(), 30_000);
    } catch (err) {
      toast.error('Failed to start image regeneration', {
        description: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setRegenerating(false);
    }
  };

  // Resolve a chapter's image to the static URL the storage mount
  // serves. ``image_path`` is stored as an absolute path on the
  // server's disk; we strip the storage prefix to derive the URL
  // path. If the path doesn't include the storage segment, fall
  // back to the raw path.
  const imageUrlFor = (imagePath: string): string => {
    const idx = imagePath.indexOf('audiobooks/');
    if (idx >= 0) return `/storage/${imagePath.slice(idx)}`.replace(/\\/g, '/');
    return imagePath.replace(/\\/g, '/');
  };

  const active = openChapter !== null ? chapters[openChapter] : null;

  return (
    <Card padding="md">
      <div className="flex items-center justify-between mb-3 gap-2 flex-wrap">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-txt-primary flex items-center gap-2">
            <ImageIcon size={14} className="text-accent" />
            Chapter Illustrations
          </h3>
          <p className="text-[11px] text-txt-tertiary mt-0.5">
            {chaptersWithImages} of {chapters.length} chapters have an
            image. Click to view full-size or regenerate.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
        {chapters.map((ch, i) => {
          const hasImage = !!ch.image_path;
          return (
            <button
              key={i}
              type="button"
              onClick={() => {
                setOpenChapter(i);
                setPromptOverride(ch.visual_prompt ?? '');
              }}
              className="group relative aspect-video rounded-md border border-border bg-bg-elevated overflow-hidden hover:border-accent/50 transition-colors duration-fast text-left"
              title={ch.title || `Chapter ${i + 1}`}
            >
              {hasImage ? (
                <img
                  src={imageUrlFor(ch.image_path as string)}
                  alt={ch.title || `Chapter ${i + 1}`}
                  loading="lazy"
                  decoding="async"
                  className="absolute inset-0 w-full h-full object-cover"
                  draggable={false}
                />
              ) : (
                <div className="absolute inset-0 flex items-center justify-center text-txt-muted">
                  <ImageIcon size={24} />
                </div>
              )}
              <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 to-transparent p-1.5">
                <div className="text-[10px] font-mono text-white/70">
                  Ch {i + 1}
                </div>
                <div className="text-[11px] text-white truncate font-medium">
                  {ch.title || `Chapter ${i + 1}`}
                </div>
              </div>
            </button>
          );
        })}
      </div>

      {/* Detail / regen modal */}
      <Dialog
        open={openChapter !== null}
        onClose={() => {
          setOpenChapter(null);
          setPromptOverride('');
        }}
        title={
          active
            ? `Chapter ${openChapter! + 1} — ${active.title || 'Untitled'}`
            : ''
        }
        description="Preview the current illustration and regenerate it with an optional custom prompt."
        maxWidth="lg"
      >
        {active && (
          <div className="space-y-3">
            <div className="rounded-md overflow-hidden border border-border bg-black/40">
              {active.image_path ? (
                <img
                  src={imageUrlFor(active.image_path as string)}
                  alt={active.title ?? ''}
                  className="w-full max-h-[420px] object-contain"
                />
              ) : (
                <div className="aspect-video flex items-center justify-center text-txt-muted">
                  <span className="text-xs">No image yet</span>
                </div>
              )}
            </div>
            <Textarea
              label="Visual prompt (optional)"
              value={promptOverride}
              onChange={(e) => setPromptOverride(e.target.value)}
              placeholder="Override the auto-derived prompt — useful when the chapter title alone produces a weak image."
              hint="Leave blank to reuse the auto-derived prompt (chapter title + mood + first 200 chars of text)."
              rows={3}
            />
          </div>
        )}
        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => {
              setOpenChapter(null);
              setPromptOverride('');
            }}
          >
            Close
          </Button>
          <Button
            variant="primary"
            loading={regenerating}
            disabled={openChapter === null}
            onClick={() =>
              openChapter !== null && void handleRegenerate(openChapter)
            }
          >
            <Sparkles size={13} />
            Regenerate Image
          </Button>
        </DialogFooter>
      </Dialog>
    </Card>
  );
}

export default AudiobookDetail;
