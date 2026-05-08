import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useToast } from '@/components/ui/Toast';
import { Link } from 'react-router-dom';
import {
  Plus,
  Trash2,
  Download,
  Film,
  Play,
  Pause,
  Mic,
  CheckCircle,
  XCircle,
  FileAudio,
  X,
  Clock,
  Type,
  ChevronDown,
  ChevronUp,
  Headphones,
  Image as ImageIcon,
  Users,
  Sparkles,
  Monitor,
  Smartphone,
  Subtitles,
} from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Badge } from '@/components/ui/Badge';
import { Spinner } from '@/components/ui/Spinner';
import { EmptyState } from '@/components/ui/EmptyState';
import { Dialog, DialogFooter } from '@/components/ui/Dialog';
import { audiobooks as audiobooksApi, voiceProfiles as voiceProfilesApi, ApiError } from '@/lib/api';
import { TierGatePlaceholder } from '@/components/TierGatePlaceholder';
import type { Audiobook, AudiobookCreate, VoiceProfile } from '@/types';

// ---------------------------------------------------------------------------
// Polling interval (ms)
// ---------------------------------------------------------------------------

const POLL_INTERVAL = 5000;

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
// Audiobooks Page
// ---------------------------------------------------------------------------

function Audiobooks() {
  const { toast } = useToast();
  const [audiobookList, setAudiobookList] = useState<Audiobook[]>([]);
  const [voiceProfileList, setVoiceProfileList] = useState<VoiceProfile[]>([]);
  const [loading, setLoading] = useState(true);
  // Captures the initial-fetch error so we can render the tier-gate
  // upgrade placeholder instead of a generic toast when the API
  // returns 402 (audiobooks is a Pro+ feature).
  const [loadError, setLoadError] = useState<unknown>(null);
  const [creating, setCreating] = useState(false);
  const [showCreator, setShowCreator] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [playingId, setPlayingId] = useState<string | null>(null);
  const [playingVoice, setPlayingVoice] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // Form state
  const [title, setTitle] = useState('');
  const [text, setText] = useState('');
  const [selectedVoice, setSelectedVoice] = useState('');
  const [generateVideo, setGenerateVideo] = useState(false);
  const [outputFormat, setOutputFormat] = useState<string>('audio_only');
  const [speed, setSpeed] = useState(1.0);
  const [pitch, setPitch] = useState(1.0);
  const [musicEnabled, setMusicEnabled] = useState(false);
  const [musicMood, setMusicMood] = useState('calm');
  const [voiceCasting, setVoiceCasting] = useState<Record<string, string>>({});
  const [coverPreview, setCoverPreview] = useState<string | null>(null);
  const [videoOrientation, setVideoOrientation] = useState<'landscape' | 'vertical'>('vertical');
  const [captionStyle, setCaptionStyle] = useState<string | null>('youtube_highlight');
  const [imageGenEnabled, setImageGenEnabled] = useState(false);
  const [perChapterMusic, setPerChapterMusic] = useState(false);

  // AI Creator dialog state (single-form, no wizard steps)
  const [showAiDialog, setShowAiDialog] = useState(false);
  const [aiConcept, setAiConcept] = useState('');
  const [aiCharacters, setAiCharacters] = useState<
    Array<{ name: string; description: string; gender: string; voice_profile_id: string | null }>
  >([{ name: 'Narrator', description: 'Omniscient narrator', gender: 'male', voice_profile_id: null }]);
  const [aiMinutes, setAiMinutes] = useState(5);
  const [aiMood, setAiMood] = useState('neutral');
  const [aiOutputFormat, setAiOutputFormat] = useState<string>('audio_only');
  const [aiMusicEnabled, setAiMusicEnabled] = useState(false);
  const [aiMusicMood, setAiMusicMood] = useState('calm');
  const [aiSpeed, setAiSpeed] = useState(1.0);
  const [aiPitch, setAiPitch] = useState(1.0);
  const [aiSubmitting, setAiSubmitting] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);
  const [aiImageGen, setAiImageGen] = useState(false);
  const [aiPerChapterMusic, setAiPerChapterMusic] = useState(false);

  // Polling ref for generating audiobooks
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // WebSocket progress for generating audiobooks
  const [wsProgress, setWsProgress] = useState<Record<string, { step: string; progress_pct: number; message: string }>>({});
  const wsRefs = useRef<Record<string, { close: () => void }>>({});

  // ─── Auto-detect speakers from text ──────────────────────────────────

  const detectedSpeakers = useMemo(() => {
    const matches = text.match(/^\[([^\]]+)\]/gm);
    if (!matches) return [];
    return [...new Set(matches.map(m => m.slice(1, -1)))];
  }, [text]);

  // ─── Auto-detect chapters from text ─────────────────────────────────

  const detectedChapters = useMemo(() => {
    const parts = text.split(/^##\s+/m);
    if (parts.length <= 1) return [];
    return parts.slice(1).map(p => (p.split('\n')[0] ?? '').trim());
  }, [text]);

  // ─── Fetch data ──────────────────────────────────────────────────────

  const fetchAudiobooks = useCallback(async () => {
    try {
      const res = await audiobooksApi.list();
      setAudiobookList(res);
      setLoadError(null);
      return res;
    } catch (err) {
      // 402 is owned by the tier-gate placeholder render branch — don't
      // toast over it (the user gets a richer upgrade card instead).
      if (err instanceof ApiError && err.status === 402) {
        setLoadError(err);
        return [];
      }
      toast.error('Failed to load audiobooks', { description: String(err) });
      return [];
    }
  }, [toast]);

  const fetchVoiceProfiles = useCallback(async () => {
    try {
      const res = await voiceProfilesApi.list();
      setVoiceProfileList(res);
    } catch (err) {
      toast.error('Failed to load voice profiles', { description: String(err) });
    }
  }, [toast]);

  useEffect(() => {
    Promise.all([fetchAudiobooks(), fetchVoiceProfiles()])
      .finally(() => setLoading(false));
  }, [fetchAudiobooks, fetchVoiceProfiles]);

  // ─── Polling for generating audiobooks ───────────────────────────────

  const startPolling = useCallback(() => {
    if (pollingRef.current) return;

    pollingRef.current = setInterval(async () => {
      const list = await fetchAudiobooks();
      const hasGenerating = list.some((ab) => ab.status === 'generating');
      if (!hasGenerating && pollingRef.current) {
        clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
    }, POLL_INTERVAL);
  }, [fetchAudiobooks]);

  // Check if we need to start polling on mount
  useEffect(() => {
    if (audiobookList.some((ab) => ab.status === 'generating')) {
      startPolling();
    }
    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
    };
  }, [audiobookList, startPolling]);

  // WebSocket connections for generating audiobooks
  useEffect(() => {
    const generating = audiobookList.filter((ab) => ab.status === 'generating');
    const activeIds = new Set(generating.map((ab) => ab.id));

    // Close WS for audiobooks no longer generating
    for (const [id, handle] of Object.entries(wsRefs.current)) {
      if (!activeIds.has(id)) {
        handle.close();
        delete wsRefs.current[id];
      }
    }

    // Open WS for newly generating audiobooks
    for (const ab of generating) {
      if (wsRefs.current[ab.id]) continue;

      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const host = window.location.host;
      const wsUrl = `${proto}//${host}/ws/progress/audiobook/${ab.id}`;
      const abId = ab.id;

      try {
        const ws = new WebSocket(wsUrl);

        ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            if (data.step && data.progress_pct !== undefined) {
              setWsProgress((prev) => ({ ...prev, [abId]: data }));
            }
            if (data.step === 'done') {
              void fetchAudiobooks();
            }
          } catch { /* ignore */ }
        };

        ws.onerror = () => { /* onclose handles */ };
        ws.onclose = () => { delete wsRefs.current[abId]; };
        wsRefs.current[abId] = { close: () => ws.close() };
      } catch { /* ignore WS creation errors */ }
    }
  }, [audiobookList, fetchAudiobooks]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      for (const h of Object.values(wsRefs.current)) h.close();
      wsRefs.current = {};
    };
  }, []);

  // ─── Create audiobook ────────────────────────────────────────────────

  const handleCreate = async () => {
    if (!title.trim() || !text.trim() || !selectedVoice) return;
    setCreating(true);
    try {
      const payload: AudiobookCreate = {
        title: title.trim(),
        text: text.trim(),
        voice_profile_id: selectedVoice,
        output_format: outputFormat as 'audio_only' | 'audio_image' | 'audio_video',
        speed,
        pitch,
        music_enabled: musicEnabled,
        music_mood: musicEnabled ? musicMood : undefined,
        voice_casting: detectedSpeakers.length > 1 ? voiceCasting : undefined,
        video_orientation: outputFormat !== 'audio_only' ? videoOrientation : undefined,
        caption_style_preset: outputFormat !== 'audio_only' ? captionStyle : undefined,
        image_generation_enabled: imageGenEnabled && outputFormat !== 'audio_only',
        per_chapter_music: perChapterMusic && musicEnabled,
      };
      await audiobooksApi.create(payload);
      setShowCreator(false);
      resetForm();
      await fetchAudiobooks();
      startPolling();
      toast.success('Audiobook created', { description: 'Generation has started.' });
    } catch (err) {
      toast.error('Failed to create audiobook', { description: String(err) });
    } finally {
      setCreating(false);
    }
  };

  const resetForm = () => {
    setTitle('');
    setText('');
    setSelectedVoice('');
    setGenerateVideo(false);
    setOutputFormat('audio_only');
    setSpeed(1.0);
    setPitch(1.0);
    setMusicEnabled(false);
    setMusicMood('calm');
    setVoiceCasting({});
    setCoverPreview(null);
    setVideoOrientation('vertical');
    setCaptionStyle('youtube_highlight');
    setImageGenEnabled(false);
    setPerChapterMusic(false);
  };

  // ─── Cover image upload handler ──────────────────────────────────────

  const handleCoverUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      setCoverPreview(reader.result as string);
    };
    reader.readAsDataURL(file);
  };

  // ─── Delete audiobook ────────────────────────────────────────────────

  const handleDelete = async (id: string) => {
    setDeleting(id);
    try {
      await audiobooksApi.delete(id);
      toast.success('Audiobook deleted');
      void fetchAudiobooks();
    } catch (err) {
      toast.error('Failed to delete audiobook', { description: String(err) });
    } finally {
      setDeleting(null);
    }
  };

  // ─── Audio playback for audiobook list ───────────────────────────────

  const handlePlayPause = (audiobookId: string) => {
    document.querySelectorAll('audio').forEach((a) => {
      if (a.id !== `ab-audio-${audiobookId}`) {
        (a as HTMLAudioElement).pause();
        (a as HTMLAudioElement).currentTime = 0;
      }
    });

    const audio = document.getElementById(`ab-audio-${audiobookId}`) as HTMLAudioElement | null;
    if (!audio) return;

    if (audio.paused) {
      audio.play().catch(() => {});
      setPlayingId(audiobookId);
      audio.onended = () => setPlayingId(null);
    } else {
      audio.pause();
      setPlayingId(null);
    }
  };

  // ─── Voice preview in creator ────────────────────────────────────────

  const handleVoicePreview = (e: React.MouseEvent, profileId: string) => {
    e.stopPropagation();
    document.querySelectorAll('audio').forEach((a) => {
      if (a.id !== `vp-preview-${profileId}`) {
        (a as HTMLAudioElement).pause();
        (a as HTMLAudioElement).currentTime = 0;
      }
    });

    const audio = document.getElementById(`vp-preview-${profileId}`) as HTMLAudioElement | null;
    if (!audio) return;

    if (audio.paused) {
      audio.play().catch(() => {});
      setPlayingVoice(profileId);
      audio.onended = () => setPlayingVoice(null);
      audio.onpause = () => setPlayingVoice(null);
    } else {
      audio.pause();
      audio.currentTime = 0;
      setPlayingVoice(null);
    }
  };

  // ─── AI Creator handlers ─────────────────────────────────────────────

  const openAiDialog = () => {
    setShowAiDialog(true);
    setAiConcept('');
    setAiCharacters([
      { name: 'Narrator', description: 'Omniscient narrator', gender: 'male', voice_profile_id: null },
    ]);
    setAiMinutes(5);
    setAiMood('neutral');
    setAiOutputFormat('audio_only');
    setAiMusicEnabled(false);
    setAiMusicMood('calm');
    setAiSpeed(1.0);
    setAiPitch(1.0);
    setAiError(null);
  };

  const closeAiDialog = () => {
    setShowAiDialog(false);
  };

  const addCharacter = () => {
    setAiCharacters(prev => [
      ...prev,
      { name: '', description: '', gender: 'male', voice_profile_id: null },
    ]);
  };

  const removeCharacter = (index: number) => {
    setAiCharacters(prev => prev.filter((_, i) => i !== index));
  };

  const updateCharacter = (
    index: number,
    field: 'name' | 'description' | 'gender' | 'voice_profile_id',
    value: string | null,
  ) => {
    setAiCharacters(prev =>
      prev.map((c, i) => {
        if (i !== index) return c;
        const updated = { ...c, [field]: value };
        // When gender changes, clear voice_profile_id so the user picks a new one
        if (field === 'gender') {
          updated.voice_profile_id = null;
        }
        return updated;
      }),
    );
  };

  const hasAssignedVoice = aiCharacters.some(c => c.voice_profile_id);

  const handleAiSubmit = async () => {
    if (!aiConcept.trim() || aiConcept.trim().length < 10 || !hasAssignedVoice) return;
    setAiSubmitting(true);
    setAiError(null);
    try {
      const validChars = aiCharacters
        .filter(c => c.name.trim())
        .map(c => ({
          name: c.name.trim(),
          description: c.description.trim() || c.name.trim(),
          gender: c.gender,
          voice_profile_id: c.voice_profile_id,
        }));

      await audiobooksApi.createAI({
        concept: aiConcept.trim(),
        characters:
          validChars.length > 0
            ? validChars
            : [{ name: 'Narrator', description: 'Omniscient narrator', gender: 'male', voice_profile_id: null }],
        target_minutes: aiMinutes,
        mood: aiMood,
        output_format: aiOutputFormat,
        music_enabled: aiMusicEnabled,
        music_mood: aiMusicEnabled ? aiMusicMood : undefined,
        speed: aiSpeed,
        pitch: aiPitch,
        image_generation_enabled: aiImageGen && aiOutputFormat !== 'audio_only',
        per_chapter_music: aiPerChapterMusic && aiMusicEnabled,
      });

      closeAiDialog();
      await fetchAudiobooks();
      startPolling();
      toast.success('AI audiobook created', { description: 'Generation has started.' });
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to create AI audiobook';
      setAiError(msg);
      toast.error('Failed to create AI audiobook', { description: String(err) });
    } finally {
      setAiSubmitting(false);
    }
  };

  // ─── Helpers ─────────────────────────────────────────────────────────

  const getVoiceName = (voiceProfileId: string | null) => {
    if (!voiceProfileId) return 'Unknown';
    const vp = voiceProfileList.find((p) => p.id === voiceProfileId);
    return vp?.name ?? 'Unknown';
  };

  const formatDuration = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${String(secs).padStart(2, '0')}`;
  };

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const wordCount = text.trim() ? text.trim().split(/\s+/).length : 0;
  const estimatedMinutes = Math.max(1, Math.ceil(wordCount / 150));

  const getStatusBadgeVariant = (status: string) => {
    switch (status) {
      case 'done': return 'success';
      case 'failed': return 'error';
      case 'generating': return 'accent';
      default: return 'neutral';
    }
  };

  // ─── Render ──────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <Spinner size="lg" />
      </div>
    );
  }

  // Tier gate: if /audiobooks 402'd, render the upgrade card in place
  // of the rest of the page. Other errors fell through to the toast.
  if (loadError instanceof ApiError && loadError.status === 402) {
    return (
      <div className="max-w-2xl mx-auto py-8">
        <TierGatePlaceholder error={loadError} featureLabel="Text to Voice" />
      </div>
    );
  }

  return (
    <div>
      {/* Banner already shows "Text to Voice"; keep subtitle + CTAs only. */}
      <div className="flex items-center justify-between mb-8 gap-3 flex-wrap">
        <p className="text-sm text-txt-secondary">
          Transform any text into natural speech. Create audiobooks, voiceovers, podcasts.
        </p>
        <div className="flex items-center gap-2">
          <Button variant="secondary" onClick={openAiDialog}>
            <Sparkles size={14} />
            AI Create
          </Button>
          <Button
            variant={showCreator ? 'secondary' : 'primary'}
            onClick={() => setShowCreator(!showCreator)}
          >
            {showCreator ? (
              <>
                <X size={14} />
                Close
              </>
            ) : (
              <>
                <Plus size={14} />
                New Audiobook
              </>
            )}
          </Button>
        </div>
      </div>

      {/* -- AI Creator Dialog (single comprehensive form) -------------------- */}
      <Dialog
        open={showAiDialog}
        onClose={closeAiDialog}
        title="AI Audiobook Creator"
        description="Describe your story, assign voices, and generate -- all in one step"
        maxWidth="xl"
        className="max-h-[90vh] overflow-y-auto"
      >
        <div className="space-y-5">
          {/* ── Story Concept ─────────────────────────────────────────── */}
          <div>
            <label className="text-sm font-medium text-txt-primary block mb-1">Story Concept</label>
            <textarea
              value={aiConcept}
              onChange={(e) => setAiConcept(e.target.value)}
              placeholder="A detective story in 1920s Chicago where a jazz musician discovers a conspiracy..."
              className="w-full min-h-[100px] px-3 py-2 text-sm text-txt-primary bg-bg-elevated border border-border rounded-md resize-y focus:border-accent focus:shadow-accent-glow placeholder:text-txt-tertiary transition-all duration-fast"
            />
          </div>

          {/* ── Characters & Voices ───────────────────────────────────── */}
          <div className="space-y-2">
            <label className="text-sm font-medium text-txt-primary">Characters & Voices</label>
            {aiCharacters.map((char, i) => (
              <div key={i} className="p-3 bg-bg-elevated rounded-lg space-y-2">
                <div className="flex gap-2">
                  <Input
                    placeholder="Name"
                    value={char.name}
                    onChange={(e) => updateCharacter(i, 'name', e.target.value)}
                    className="w-28"
                  />
                  <Input
                    placeholder="Description"
                    value={char.description}
                    onChange={(e) => updateCharacter(i, 'description', e.target.value)}
                    className="flex-1"
                  />
                  {aiCharacters.length > 1 && (
                    <button
                      onClick={() => removeCharacter(i)}
                      className="text-error hover:text-error/80 px-1 shrink-0"
                    >
                      <X size={14} />
                    </button>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  {/* Gender toggle */}
                  <button
                    onClick={() => updateCharacter(i, 'gender', 'male')}
                    className={`px-2 py-0.5 text-xs rounded border transition ${
                      char.gender === 'male'
                        ? 'bg-blue-500/20 text-blue-400 border-blue-500/40'
                        : 'bg-bg-surface text-txt-tertiary border-border hover:border-border-hover'
                    }`}
                  >
                    &#9794; Male
                  </button>
                  <button
                    onClick={() => updateCharacter(i, 'gender', 'female')}
                    className={`px-2 py-0.5 text-xs rounded border transition ${
                      char.gender === 'female'
                        ? 'bg-pink-500/20 text-pink-400 border-pink-500/40'
                        : 'bg-bg-surface text-txt-tertiary border-border hover:border-border-hover'
                    }`}
                  >
                    &#9792; Female
                  </button>
                  {/* Voice dropdown filtered by gender */}
                  <select
                    value={char.voice_profile_id || ''}
                    onChange={(e) => updateCharacter(i, 'voice_profile_id', e.target.value || null)}
                    className="flex-1 bg-bg-surface border border-border rounded px-2 py-1 text-sm text-txt-primary"
                  >
                    <option value="">Auto-assign</option>
                    {voiceProfileList.filter(v => v.gender === char.gender).length > 0 && (
                      <optgroup label={char.gender === 'female' ? '&#9792; Female' : '&#9794; Male'}>
                        {voiceProfileList
                          .filter(v => v.gender === char.gender)
                          .map(v => (
                            <option key={v.id} value={v.id}>
                              {v.name}
                            </option>
                          ))}
                      </optgroup>
                    )}
                    {voiceProfileList.filter(v => v.gender !== char.gender).length > 0 && (
                      <optgroup label="Other voices">
                        {voiceProfileList
                          .filter(v => v.gender !== char.gender)
                          .map(v => (
                            <option key={v.id} value={v.id}>
                              {v.name}
                            </option>
                          ))}
                      </optgroup>
                    )}
                  </select>
                </div>
              </div>
            ))}
            <Button variant="ghost" size="sm" onClick={addCharacter}>
              <Plus size={12} /> Add Character
            </Button>
          </div>

          {/* ── Target Length & Mood ───────────────────────────────────── */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="text-sm font-medium text-txt-primary block mb-1">Target Length</label>
              <select
                value={aiMinutes}
                onChange={(e) => setAiMinutes(parseFloat(e.target.value))}
                className="w-full bg-bg-elevated border border-border rounded px-2 py-1.5 text-sm text-txt-primary"
              >
                {[2.5, 5, 7.5, 10, 15, 20, 30, 45, 60, 90, 120, 180].map(m => (
                  <option key={m} value={m}>{m} minutes</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-sm font-medium text-txt-primary block mb-1">Mood</label>
              <select
                value={aiMood}
                onChange={(e) => setAiMood(e.target.value)}
                className="w-full bg-bg-elevated border border-border rounded px-2 py-1.5 text-sm text-txt-primary"
              >
                <option value="neutral">Neutral</option>
                <option value="noir, mysterious">Noir / Mystery</option>
                <option value="fantasy, epic">Fantasy / Epic</option>
                <option value="comedy, lighthearted">Comedy</option>
                <option value="thriller, suspenseful">Thriller</option>
                <option value="calm, educational">Educational</option>
                <option value="horror, dark">Horror</option>
              </select>
            </div>
          </div>

          {/* ── Output Format ─────────────────────────────────────────── */}
          <div>
            <label className="text-sm font-medium text-txt-primary block mb-2">Output Format</label>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {[
                { value: 'audio_only', label: 'Audio Only', desc: 'WAV + MP3 files', icon: Headphones },
                { value: 'audio_image', label: 'Audio + Image', desc: 'Video with cover art', icon: ImageIcon },
                { value: 'audio_video', label: 'Audio + Video', desc: 'MP4 with background', icon: Film },
              ].map(fmt => (
                <div
                  key={fmt.value}
                  onClick={() => setAiOutputFormat(fmt.value)}
                  className={`p-3 rounded-lg border cursor-pointer text-center transition ${
                    aiOutputFormat === fmt.value
                      ? 'border-accent bg-accent/10 ring-1 ring-accent/30'
                      : 'border-border hover:border-border-hover'
                  }`}
                >
                  <fmt.icon size={20} className="mx-auto mb-1.5 text-txt-secondary" />
                  <div className="text-sm font-medium text-txt-primary">{fmt.label}</div>
                  <div className="text-[10px] text-txt-tertiary">{fmt.desc}</div>
                </div>
              ))}
            </div>
          </div>

          {/* ── Background Music ──────────────────────────────────────── */}
          <div className="space-y-2">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={aiMusicEnabled}
                onChange={(e) => setAiMusicEnabled(e.target.checked)}
                className="w-4 h-4 rounded accent-accent"
              />
              <span className="text-sm text-txt-primary">Background Music</span>
            </label>
            {aiMusicEnabled && (
              <select
                value={aiMusicMood}
                onChange={(e) => setAiMusicMood(e.target.value)}
                className="w-full text-xs bg-bg-elevated border border-border rounded px-2 py-1.5 text-txt-primary"
              >
                <option value="calm">Calm & Relaxing</option>
                <option value="upbeat">Upbeat & Energetic</option>
                <option value="dramatic">Dramatic & Cinematic</option>
                <option value="mysterious">Mysterious & Dark</option>
                <option value="playful">Playful & Fun</option>
              </select>
            )}
          </div>

          {/* ── AI Enhancements ────────────────────────────────────────── */}
          {aiOutputFormat !== 'audio_only' && (
            <div className="space-y-2">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={aiImageGen}
                  onChange={(e) => setAiImageGen(e.target.checked)}
                  className="w-4 h-4 rounded accent-accent"
                />
                <span className="text-sm text-txt-primary">Generate chapter images via AI</span>
              </label>
              <p className="text-[10px] text-txt-tertiary ml-6">
                Creates unique illustrations per chapter with smooth Ken Burns transitions
              </p>
            </div>
          )}
          {aiMusicEnabled && (
            <div className="space-y-2">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={aiPerChapterMusic}
                  onChange={(e) => setAiPerChapterMusic(e.target.checked)}
                  className="w-4 h-4 rounded accent-accent"
                />
                <span className="text-sm text-txt-primary">Per-chapter music moods</span>
              </label>
              <p className="text-[10px] text-txt-tertiary ml-6">
                Different music moods for each chapter with crossfade transitions
              </p>
            </div>
          )}

          {/* ── Speed & Pitch ─────────────────────────────────────────── */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="text-xs text-txt-tertiary flex justify-between">
                Speed <span>{aiSpeed.toFixed(1)}x</span>
              </label>
              <input
                type="range"
                min="0.5"
                max="2.0"
                step="0.1"
                value={aiSpeed}
                onChange={e => setAiSpeed(parseFloat(e.target.value))}
                className="w-full h-1.5 rounded-full accent-accent"
              />
            </div>
            <div>
              <label className="text-xs text-txt-tertiary flex justify-between">
                Pitch <span>{aiPitch.toFixed(1)}x</span>
              </label>
              <input
                type="range"
                min="0.5"
                max="2.0"
                step="0.1"
                value={aiPitch}
                onChange={e => setAiPitch(parseFloat(e.target.value))}
                className="w-full h-1.5 rounded-full accent-accent"
              />
            </div>
          </div>

          {/* ── Error ─────────────────────────────────────────────────── */}
          {aiError && (
            <div className="flex items-start gap-2 text-xs text-error bg-error-muted p-2.5 rounded-md border border-error/20">
              <XCircle size={12} className="shrink-0 mt-0.5" />
              <span>{aiError}</span>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={closeAiDialog}>Cancel</Button>
          <Button
            variant="primary"
            loading={aiSubmitting}
            disabled={!aiConcept.trim() || aiConcept.trim().length < 10 || !hasAssignedVoice}
            onClick={() => void handleAiSubmit()}
          >
            <Sparkles size={14} /> Generate Audiobook
          </Button>
        </DialogFooter>
      </Dialog>

      {/* -- Creator Section ----------------------------------------------- */}
      {showCreator && (
        <Card padding="lg" className="mb-8 border-accent/30">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            {/* Left: Text input */}
            <div className="lg:col-span-8">
              <Input
                label="Title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="My Audiobook"
                autoFocus
              />

              {/* Output Format */}
              <div className="mt-4 mb-4">
                <label className="text-sm font-medium text-txt-primary block mb-2">Output Format</label>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                  {[
                    { value: 'audio_only', label: 'Audio Only', desc: 'WAV + MP3 files', icon: Headphones },
                    { value: 'audio_image', label: 'Audio + Image', desc: 'Video with cover art', icon: ImageIcon },
                    { value: 'audio_video', label: 'Audio + Video', desc: 'MP4 with background', icon: Film },
                  ].map(fmt => (
                    <div key={fmt.value}
                      onClick={() => setOutputFormat(fmt.value)}
                      className={`p-3 rounded-lg border cursor-pointer text-center transition ${
                        outputFormat === fmt.value
                          ? 'border-accent bg-accent/10 ring-1 ring-accent/30'
                          : 'border-border hover:border-border-hover'
                      }`}>
                      <fmt.icon size={20} className="mx-auto mb-1.5 text-txt-secondary" />
                      <div className="text-sm font-medium text-txt-primary">{fmt.label}</div>
                      <div className="text-[10px] text-txt-tertiary">{fmt.desc}</div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Cover Image Upload (shows when audio_image selected) */}
              {outputFormat === 'audio_image' && (
                <div className="mb-4 p-3 border border-dashed border-border rounded-lg text-center">
                  <ImageIcon size={24} className="mx-auto mb-2 text-txt-tertiary" />
                  <p className="text-sm text-txt-secondary">Upload cover image</p>
                  <input type="file" accept="image/*" onChange={handleCoverUpload} className="mt-2 text-xs" />
                  {coverPreview && <img src={coverPreview} className="mt-2 mx-auto max-h-32 rounded" />}
                </div>
              )}

              {/* Orientation Toggle (video outputs only) */}
              {outputFormat !== 'audio_only' && (
                <div className="mb-4">
                  <label className="text-sm font-medium text-txt-primary block mb-2">Orientation</label>
                  <div className="flex gap-2">
                    {([
                      { value: 'vertical', label: 'Vertical / Shorts', sub: '1080x1920', Icon: Smartphone },
                      { value: 'landscape', label: 'Landscape', sub: '1920x1080', Icon: Monitor },
                    ] as const).map(({ value, label, sub, Icon }) => (
                      <button
                        key={value}
                        type="button"
                        onClick={() => setVideoOrientation(value)}
                        className={[
                          'flex-1 flex items-center gap-2.5 px-3 py-2.5 rounded-lg border transition text-left',
                          videoOrientation === value
                            ? 'border-accent bg-accent/10 ring-1 ring-accent/30'
                            : 'border-border hover:border-border-hover bg-bg-elevated',
                        ].join(' ')}
                      >
                        <Icon size={18} className={videoOrientation === value ? 'text-accent' : 'text-txt-tertiary'} />
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
              {outputFormat !== 'audio_only' && (
                <div className="mb-4">
                  <label className="text-sm font-medium text-txt-primary flex items-center gap-1.5 mb-2">
                    <Subtitles size={14} className="text-txt-tertiary" />
                    Caption Style
                  </label>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                    {CAPTION_PRESETS.map((preset) => (
                      <div
                        key={String(preset.value)}
                        onClick={() => setCaptionStyle(preset.value)}
                        className={[
                          'p-2.5 rounded-lg border cursor-pointer transition text-center',
                          captionStyle === preset.value
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

              {/* AI Chapter Images (video outputs only) */}
              {outputFormat !== 'audio_only' && (
                <div className="mb-4">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={imageGenEnabled}
                      onChange={(e) => setImageGenEnabled(e.target.checked)}
                      className="rounded border-border text-accent focus:ring-accent"
                    />
                    <span className="text-sm font-medium text-txt-primary flex items-center gap-1.5">
                      <ImageIcon size={14} className="text-txt-tertiary" />
                      Generate chapter images via AI
                    </span>
                  </label>
                  <p className="text-[10px] text-txt-tertiary mt-1 ml-6">
                    Creates unique AI-generated illustrations for each chapter with Ken Burns transitions
                  </p>
                </div>
              )}

              {/* Per-chapter music */}
              {musicEnabled && (
                <div className="mb-4">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={perChapterMusic}
                      onChange={(e) => setPerChapterMusic(e.target.checked)}
                      className="rounded border-border text-accent focus:ring-accent"
                    />
                    <span className="text-sm font-medium text-txt-primary">
                      Per-chapter music moods
                    </span>
                  </label>
                  <p className="text-[10px] text-txt-tertiary mt-1 ml-6">
                    Use different music moods for each chapter with smooth crossfade transitions
                  </p>
                </div>
              )}

              <div className="relative">
                <label className="text-xs font-medium text-txt-secondary block mb-1">
                  Your Text
                </label>
                <textarea
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  placeholder="Paste your text here... chapters, articles, stories -- any length."
                  className={[
                    'w-full min-h-[400px] px-4 py-3 text-sm text-txt-primary leading-relaxed',
                    'bg-bg-elevated border border-border rounded-md resize-y',
                    'focus:border-accent focus:shadow-accent-glow',
                    'placeholder:text-txt-tertiary',
                    'transition-all duration-fast',
                  ].join(' ')}
                />
                <div className="absolute bottom-4 right-4 flex items-center gap-3 text-xs text-txt-tertiary bg-bg-surface/90 backdrop-blur-sm px-2.5 py-1 rounded-md border border-border/50">
                  <span className="flex items-center gap-1">
                    <Type size={10} />
                    {text.length.toLocaleString()} chars
                  </span>
                  <span className="text-border-strong">&middot;</span>
                  <span>{wordCount.toLocaleString()} words</span>
                  <span className="text-border-strong">&middot;</span>
                  <span className="flex items-center gap-1">
                    <Clock size={10} />
                    ~{estimatedMinutes} min
                  </span>
                </div>
              </div>

              {/* Chapter detection */}
              {detectedChapters.length > 0 && (
                <div className="mt-3 p-2 bg-bg-elevated rounded text-xs">
                  <span className="text-txt-tertiary">Chapters: </span>
                  {detectedChapters.map((ch, i) => (
                    <Badge key={i} variant="neutral" className="mr-1 mb-1">{ch}</Badge>
                  ))}
                </div>
              )}
            </div>

            {/* Right: Voice picker + options */}
            <div className="lg:col-span-4 flex flex-col">
              <div className="flex-1">
                <label className="text-xs font-medium text-txt-secondary block mb-2">
                  Choose Voice
                </label>

                {voiceProfileList.length === 0 ? (
                  <div className="p-6 border border-border rounded-lg bg-bg-elevated text-center">
                    <Mic size={24} className="mx-auto mb-2 text-txt-tertiary opacity-50" />
                    <p className="text-sm text-txt-secondary">No voice profiles available.</p>
                    <p className="text-xs text-txt-tertiary mt-1">
                      Create voice profiles in Settings first.
                    </p>
                  </div>
                ) : (
                  <div className="space-y-2 max-h-[300px] overflow-y-auto pr-1 scrollbar-thin">
                    {voiceProfileList.map((vp) => (
                      <div
                        key={vp.id}
                        onClick={() => setSelectedVoice(vp.id)}
                        className={[
                          'p-3 rounded-lg border cursor-pointer transition-all duration-fast',
                          selectedVoice === vp.id
                            ? 'border-accent bg-accent/10 ring-1 ring-accent/30'
                            : 'border-border hover:border-border-hover bg-bg-surface',
                        ].join(' ')}
                      >
                        <div className="flex items-center justify-between">
                          <div className="min-w-0 flex-1">
                            <span className="text-sm font-medium text-txt-primary truncate block">
                              {vp.name}
                            </span>
                            <Badge variant="neutral" className="mt-1 text-[9px]">
                              {vp.provider}
                            </Badge>
                          </div>
                          {vp.sample_audio_path && (
                            <button
                              onClick={(e) => handleVoicePreview(e, vp.id)}
                              className="w-7 h-7 rounded-full bg-accent/20 flex items-center justify-center hover:bg-accent/30 transition-colors duration-fast shrink-0 ml-2"
                            >
                              {playingVoice === vp.id ? (
                                <Pause size={12} className="text-accent" />
                              ) : (
                                <Play size={12} className="text-accent" />
                              )}
                            </button>
                          )}
                          {vp.sample_audio_path && (
                            <audio
                              id={`vp-preview-${vp.id}`}
                              src={`/storage/${vp.sample_audio_path}`}
                              preload="none"
                            />
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Voice Casting Detection */}
              {detectedSpeakers.length > 1 && (
                <div className="mt-4 p-3 bg-accent/5 rounded-lg border border-accent/20">
                  <div className="flex items-center gap-2 mb-2">
                    <Users size={14} className="text-accent" />
                    <span className="text-sm font-medium text-txt-primary">
                      {detectedSpeakers.length} speakers detected
                    </span>
                  </div>
                  <div className="space-y-2">
                    {detectedSpeakers.map(speaker => (
                      <div key={speaker} className="flex items-center gap-2">
                        <span className="text-xs font-mono text-accent w-24 truncate">[{speaker}]</span>
                        <select
                          value={voiceCasting[speaker] || selectedVoice}
                          onChange={e => setVoiceCasting(prev => ({...prev, [speaker]: e.target.value}))}
                          className="flex-1 text-xs bg-bg-elevated border border-border rounded px-2 py-1 text-txt-primary"
                        >
                          {voiceProfileList.map(vp => (
                            <option key={vp.id} value={vp.id}>{vp.name}</option>
                          ))}
                        </select>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Audio Controls */}
              <div className="space-y-3 pt-3 mt-3 border-t border-border">
                <div>
                  <label className="text-xs text-txt-tertiary flex justify-between">
                    Speed <span>{speed.toFixed(1)}x</span>
                  </label>
                  <input type="range" min="0.5" max="2.0" step="0.1" value={speed}
                    onChange={e => setSpeed(parseFloat(e.target.value))}
                    className="w-full h-1.5 rounded-full accent-accent" />
                </div>
                <div>
                  <label className="text-xs text-txt-tertiary flex justify-between">
                    Pitch <span>{pitch.toFixed(1)}x</span>
                  </label>
                  <input type="range" min="0.5" max="2.0" step="0.1" value={pitch}
                    onChange={e => setPitch(parseFloat(e.target.value))}
                    className="w-full h-1.5 rounded-full accent-accent" />
                </div>

                {/* Background Music */}
                <label className="flex items-center gap-2 cursor-pointer">
                  <input type="checkbox" checked={musicEnabled} onChange={e => setMusicEnabled(e.target.checked)}
                    className="w-4 h-4 rounded accent-accent" />
                  <span className="text-sm text-txt-primary">Background Music</span>
                </label>
                {musicEnabled && (
                  <select value={musicMood} onChange={e => setMusicMood(e.target.value)}
                    className="w-full text-xs bg-bg-elevated border border-border rounded px-2 py-1.5 text-txt-primary">
                    <option value="calm">Calm & Relaxing</option>
                    <option value="upbeat">Upbeat & Energetic</option>
                    <option value="dramatic">Dramatic & Cinematic</option>
                    <option value="mysterious">Mysterious & Dark</option>
                    <option value="playful">Playful & Fun</option>
                  </select>
                )}
              </div>

              {/* Options */}
              <div className="space-y-4 pt-4 mt-4 border-t border-border">
                <label className="flex items-center gap-3 cursor-pointer group">
                  <div className="relative">
                    <input
                      type="checkbox"
                      checked={generateVideo}
                      onChange={(e) => setGenerateVideo(e.target.checked)}
                      className="sr-only peer"
                    />
                    <div className={[
                      'w-9 h-5 rounded-full transition-colors duration-fast',
                      generateVideo ? 'bg-accent' : 'bg-bg-active',
                    ].join(' ')}>
                      <div className={[
                        'absolute top-0.5 w-4 h-4 rounded-full bg-white shadow-sm transition-transform duration-fast',
                        generateVideo ? 'translate-x-4' : 'translate-x-0.5',
                      ].join(' ')} />
                    </div>
                  </div>
                  <div>
                    <span className="text-sm text-txt-primary block">Generate Video (MP4)</span>
                    <p className="text-xs text-txt-tertiary">Creates a video file for YouTube upload</p>
                  </div>
                </label>

                {/* Generate button */}
                <Button
                  variant="primary"
                  size="lg"
                  className="w-full"
                  loading={creating}
                  disabled={!title.trim() || !text.trim() || !selectedVoice}
                  onClick={() => void handleCreate()}
                >
                  <Mic size={18} />
                  Generate Audiobook
                </Button>
              </div>
            </div>
          </div>
        </Card>
      )}

      {/* -- Audiobook List ------------------------------------------------ */}
      {audiobookList.length === 0 ? (
        <EmptyState
          icon={Mic}
          title="No audiobooks yet"
          description="Create your first text-to-voice project."
          action={
            !showCreator ? (
              <div className="flex items-center gap-2">
                <Button variant="secondary" onClick={openAiDialog}>
                  <Sparkles size={14} />
                  AI Create
                </Button>
                <Button variant="primary" onClick={() => setShowCreator(true)}>
                  <Plus size={14} />
                  Create Audiobook
                </Button>
              </div>
            ) : null
          }
        />
      ) : (
        <div className="space-y-3">
          {audiobookList.map((ab) => (
            <Card key={ab.id} padding="md" className="group">
              <div className="flex items-start gap-4">
                {/* Status icon */}
                <div className={[
                  'w-12 h-12 rounded-lg flex items-center justify-center flex-shrink-0',
                  ab.status === 'done' ? 'bg-success-muted' :
                  ab.status === 'generating' ? 'bg-accent-muted' :
                  ab.status === 'failed' ? 'bg-error-muted' :
                  'bg-bg-elevated',
                ].join(' ')}>
                  {ab.status === 'generating' ? (
                    <Spinner size="sm" />
                  ) : ab.status === 'done' ? (
                    <CheckCircle size={20} className="text-success" />
                  ) : ab.status === 'failed' ? (
                    <XCircle size={20} className="text-error" />
                  ) : (
                    <FileAudio size={20} className="text-txt-tertiary" />
                  )}
                </div>

                {/* Content */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <Link
                      to={`/audiobooks/${ab.id}`}
                      className="font-semibold text-txt-primary truncate hover:text-accent transition-colors duration-fast"
                    >
                      {ab.title}
                    </Link>
                    <Badge variant={getStatusBadgeVariant(ab.status)} dot>
                      {ab.status}
                    </Badge>
                  </div>

                  {/* Generation progress */}
                  {ab.status === 'generating' && (
                    <div className="mb-2">
                      {wsProgress[ab.id] ? (
                        <>
                          <div className="flex items-center gap-2 text-[10px] text-txt-tertiary mb-1">
                            <Spinner size="sm" />
                            <span className="capitalize">{wsProgress[ab.id]!.step}</span>
                            <span>{wsProgress[ab.id]!.message}</span>
                          </div>
                          <div className="w-full h-1.5 bg-bg-elevated rounded-full overflow-hidden">
                            <div
                              className="h-full bg-accent rounded-full transition-all duration-300"
                              style={{ width: `${wsProgress[ab.id]!.progress_pct}%` }}
                            />
                          </div>
                        </>
                      ) : (
                        <div className="flex items-center gap-2 text-[10px] text-txt-tertiary">
                          <Spinner size="sm" />
                          <span>Generating...</span>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Text preview with expand */}
                  <p
                    className={[
                      'text-xs text-txt-tertiary mb-2 cursor-pointer hover:text-txt-secondary transition-colors duration-fast',
                      expandedId === ab.id ? '' : 'line-clamp-2',
                    ].join(' ')}
                    onClick={() => setExpandedId(expandedId === ab.id ? null : ab.id)}
                  >
                    {(ab.text || '').slice(0, expandedId === ab.id ? 1000 : 200)}
                    {(ab.text || '').length > (expandedId === ab.id ? 1000 : 200) && '...'}
                  </p>
                  {(ab.text || '').length > 100 && (
                    <button
                      onClick={() => setExpandedId(expandedId === ab.id ? null : ab.id)}
                      className="flex items-center gap-0.5 text-[10px] text-accent hover:text-accent-hover transition-colors duration-fast mb-2"
                    >
                      {expandedId === ab.id ? (
                        <><ChevronUp size={10} /> Show less</>
                      ) : (
                        <><ChevronDown size={10} /> Show more</>
                      )}
                    </button>
                  )}

                  {/* Stats row */}
                  <div className="flex items-center gap-4 text-xs text-txt-secondary">
                    <span className="flex items-center gap-1">
                      <Mic size={10} className="text-txt-tertiary" />
                      {getVoiceName(ab.voice_profile_id)}
                    </span>
                    {ab.duration_seconds != null && (
                      <span className="flex items-center gap-1">
                        <Clock size={10} className="text-txt-tertiary" />
                        {formatDuration(ab.duration_seconds)}
                      </span>
                    )}
                    {ab.file_size_bytes != null && (
                      <span>{formatFileSize(ab.file_size_bytes)}</span>
                    )}
                    <span className="text-txt-tertiary">
                      {new Date(ab.created_at).toLocaleDateString(undefined, {
                        month: 'short',
                        day: 'numeric',
                        year: 'numeric',
                      })}
                    </span>
                  </div>

                  {/* Inline audio player + downloads */}
                  {ab.status === 'done' && ab.audio_path && (
                    <div className="mt-3 flex items-center gap-3">
                      <button
                        onClick={() => handlePlayPause(ab.id)}
                        className={[
                          'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all duration-fast',
                          playingId === ab.id
                            ? 'bg-accent text-txt-onAccent shadow-accent-glow'
                            : 'bg-accent-muted text-accent hover:bg-accent/20',
                        ].join(' ')}
                      >
                        {playingId === ab.id ? <Pause size={12} /> : <Play size={12} />}
                        {playingId === ab.id ? 'Pause' : 'Play'}
                      </button>
                      <audio
                        id={`ab-audio-${ab.id}`}
                        src={`/storage/${ab.audio_path}`}
                        preload="none"
                      />
                    </div>
                  )}

                  {/* Downloads */}
                  {ab.status === 'done' && (
                    <div className="mt-3 flex items-center gap-3">
                      {ab.audio_path && (
                        <a href={`/storage/${ab.audio_path}`} download className="text-xs text-accent flex items-center gap-1">
                          <Download size={12} /> WAV
                        </a>
                      )}
                      {ab.mp3_path && (
                        <a href={`/storage/${ab.mp3_path}`} download className="text-xs text-accent flex items-center gap-1">
                          <Download size={12} /> MP3
                        </a>
                      )}
                      {ab.video_path && (
                        <a href={`/storage/${ab.video_path}`} download className="text-xs text-accent flex items-center gap-1">
                          <Film size={12} /> MP4
                        </a>
                      )}
                    </div>
                  )}

                  {/* Chapter list with images and timing */}
                  {ab.chapters && ab.chapters.length > 1 && (
                    <div className="mt-3 space-y-1.5">
                      <div className="text-[10px] font-medium text-txt-tertiary uppercase tracking-wider">
                        Chapters ({ab.chapters.length})
                      </div>
                      <div className="grid gap-1.5">
                        {ab.chapters.map((ch, i) => (
                          <div key={i} className="flex items-center gap-2 p-1.5 rounded bg-bg-elevated/50 border border-border/30">
                            {ch.image_path && (
                              <img
                                src={`/storage/${ch.image_path}`}
                                alt={ch.title}
                                loading="lazy"
                                decoding="async"
                                className="w-10 h-10 rounded object-cover shrink-0"
                              />
                            )}
                            <div className="flex-1 min-w-0">
                              <div className="text-xs font-medium text-txt-primary truncate">{ch.title}</div>
                              <div className="flex items-center gap-2 text-[10px] text-txt-tertiary">
                                {ch.duration_seconds != null && (
                                  <span>{Math.floor(ch.duration_seconds / 60)}:{String(Math.floor(ch.duration_seconds % 60)).padStart(2, '0')}</span>
                                )}
                                {ch.music_mood && (
                                  <Badge variant="neutral" className="text-[8px] py-0">{ch.music_mood}</Badge>
                                )}
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Error message */}
                  {ab.status === 'failed' && ab.error_message && (
                    <div className="mt-2 flex items-start gap-2 text-xs text-error bg-error-muted p-2.5 rounded-md border border-error/20">
                      <XCircle size={12} className="shrink-0 mt-0.5" />
                      <span>{ab.error_message}</span>
                    </div>
                  )}
                </div>

                {/* Delete button */}
                <div className="shrink-0">
                  <Button
                    variant="ghost"
                    size="sm"
                    loading={deleting === ab.id}
                    onClick={() => void handleDelete(ab.id)}
                    className="opacity-0 group-hover:opacity-100 transition-opacity duration-fast text-txt-tertiary hover:text-error"
                  >
                    <Trash2 size={14} />
                  </Button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

export default Audiobooks;
