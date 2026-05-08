import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import {
  ArrowLeft,
  BarChart2,
  Film,
  Settings2,
  Trash2,
  LayoutTemplate,
} from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Input, Textarea } from '@/components/ui/Input';
import { Card } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Dialog, DialogFooter } from '@/components/ui/Dialog';
import { Spinner } from '@/components/ui/Spinner';
import { Breadcrumb } from '@/components/ui/Breadcrumb';
import {
  series as seriesApi,
  episodes as episodesApi,
  comfyuiWorkflows as workflowsApi,
  videoTemplates as videoTemplatesApi,
} from '@/lib/api';
import { useToast } from '@/components/ui/Toast';
import { useDocumentTitle } from '@/hooks/useDocumentTitle';
import { usePreferences } from '@/lib/usePreferences';
import type {
  Series,
  EpisodeListItem,
  EpisodeCreate,
  CaptionStyle,
  ComfyUIWorkflow,
} from '@/types';
import { DEFAULT_CAPTION_STYLE } from '@/components/captions/CaptionStyleEditor';
import { AutosaveStatusPill } from './sections/AutosaveStatusPill';
import { HeroCard } from './sections/HeroCard';
import { EpisodesTab } from './sections/EpisodesTab';
import { SetupTab } from './sections/SetupTab';
import { AnalyticsTab } from './sections/AnalyticsTab';

// ---------------------------------------------------------------------------
// Tab definition
// ---------------------------------------------------------------------------

type TabId = 'episodes' | 'setup' | 'analytics';

interface TabDef {
  id: TabId;
  label: string;
  icon: React.ElementType;
}

const TABS: TabDef[] = [
  { id: 'episodes', label: 'Episodes', icon: Film },
  { id: 'setup', label: 'Setup', icon: Settings2 },
  { id: 'analytics', label: 'Analytics', icon: BarChart2 },
];

// ---------------------------------------------------------------------------
// Series Detail Page
// ---------------------------------------------------------------------------

function SeriesDetail() {
  const { seriesId } = useParams<{ seriesId: string }>();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { toast } = useToast();

  // ── Tab state — URL param + persisted preference ─────────────────────
  // Priority: URL ?tab= param > saved pref > default 'episodes'.
  // The URL wins so external links (e.g. Dashboard trending-topics quick
  // action that passes ?tab=trending → remapped to episodes) land correctly.
  const { prefs: tabPref, update: setTabPref } = usePreferences<TabId>('series_detail_tab');

  const rawTab = searchParams.get('tab') as TabId | null;
  const validTab = rawTab && TABS.some((t) => t.id === rawTab) ? rawTab : null;
  const [activeTab, setActiveTab] = useState<TabId>(validTab ?? tabPref ?? 'episodes');

  // Keep URL + pref in sync whenever the tab changes.
  const handleTabChange = useCallback(
    (tab: TabId) => {
      setActiveTab(tab);
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        next.set('tab', tab);
        return next;
      }, { replace: true });
      void setTabPref(tab);
    },
    [setSearchParams, setTabPref],
  );

  // If the URL param changes externally (back/forward nav), sync local state.
  useEffect(() => {
    if (validTab && validTab !== activeTab) {
      setActiveTab(validTab);
    }
  }, [validTab]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Series / episodes data ────────────────────────────────────────────
  const [seriesData, setSeriesData] = useState<Series | null>(null);
  const [episodesList, setEpisodesList] = useState<EpisodeListItem[]>([]);
  const [workflows, setWorkflows] = useState<ComfyUIWorkflow[]>([]);
  const [loading, setLoading] = useState(true);
  const [deleting, setDeleting] = useState(false);

  useDocumentTitle(seriesData?.name || 'Series Detail');

  // ── Autosave state ────────────────────────────────────────────────────
  // `autosaveStatus` drives the status pill in the breadcrumb row.
  // Goes: idle → saving → saved → (1.5s later) → idle. On error we land
  // on "error" so the user knows their last change didn't make it to the
  // server. A ref tracks whether we've seen the first successful fetch —
  // edits before that shouldn't trigger a save.
  const [autosaveStatus, setAutosaveStatus] = useState<
    'idle' | 'saving' | 'saved' | 'error'
  >('idle');
  const hasLoadedOnce = useRef(false);
  const savedSignatureRef = useRef<string>('');

  // ── Edit state — basics ───────────────────────────────────────────────
  const [editName, setEditName] = useState('');
  const [editDescription, setEditDescription] = useState('');
  const [editDuration, setEditDuration] = useState('30');
  const [editStyle, setEditStyle] = useState('');
  const [editCharacter, setEditCharacter] = useState('');
  const [editLanguage, setEditLanguage] = useState('en-US');

  // Edit state — caption style
  const [editCaptionStyle, setEditCaptionStyle] =
    useState<CaptionStyle>(DEFAULT_CAPTION_STYLE);

  // Edit state — music
  const [editMusicEnabled, setEditMusicEnabled] = useState(false);
  const [editMusicMood, setEditMusicMood] = useState('upbeat');
  const [editMusicVolume, setEditMusicVolume] = useState(-14);

  // Edit state — scene mode / video workflow
  const [editSceneMode, setEditSceneMode] = useState<'image' | 'video'>('image');
  const [editVideoWorkflowId, setEditVideoWorkflowId] = useState('');

  // Edit state — YouTube channel
  const [editYoutubeChannelId, setEditYoutubeChannelId] = useState('');
  const [youtubeChannels, setYoutubeChannels] = useState<Array<{ id: string; channel_name: string }>>([]);

  // Edit state — longform
  const [editContentFormat, setEditContentFormat] = useState<
    'shorts' | 'longform' | 'music_video'
  >('shorts');
  const [editTargetMinutes, setEditTargetMinutes] = useState(30);
  const [editScenesPerChapter, setEditScenesPerChapter] = useState(8);
  const [editVisualConsistency, setEditVisualConsistency] = useState('');

  // Edit state — tone profile
  const [editTonePersona, setEditTonePersona] = useState('');
  const [editToneForbidden, setEditToneForbidden] = useState('');
  const [editToneRequiredMoves, setEditToneRequiredMoves] = useState('');
  const [editToneReadingLevel, setEditToneReadingLevel] = useState<number>(8);
  const [editToneMaxSentence, setEditToneMaxSentence] = useState<number>(18);
  const [editToneStyleSample, setEditToneStyleSample] = useState('');
  const [editToneSignaturePhrases, setEditToneSignaturePhrases] = useState('');
  const [editToneAllowListicle, setEditToneAllowListicle] = useState(false);
  const [editToneCtaBoilerplate, setEditToneCtaBoilerplate] = useState(false);

  const [editAspectRatio, setEditAspectRatio] = useState('9:16');

  // Edit state — Phase E locks (comma-separated UUIDs + strength/lora)
  const [editCharacterAssetIds, setEditCharacterAssetIds] = useState('');
  const [editCharacterStrength, setEditCharacterStrength] = useState(0.75);
  const [editCharacterLora, setEditCharacterLora] = useState('');
  const [editStyleAssetIds, setEditStyleAssetIds] = useState('');
  const [editStyleStrength, setEditStyleStrength] = useState(0.5);
  const [editStyleLora, setEditStyleLora] = useState('');

  // ── Episode action state ──────────────────────────────────────────────
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [newTopic, setNewTopic] = useState('');
  const [creatingEpisode, setCreatingEpisode] = useState(false);

  const [generatingAllDrafts, setGeneratingAllDrafts] = useState(false);
  const [addingEpisodesAi, setAddingEpisodesAi] = useState(false);

  const [trendingOpen, setTrendingOpen] = useState(false);
  const [trendingLoading, setTrendingLoading] = useState(false);
  const [trendingTopics, setTrendingTopics] = useState<
    Array<{ title: string; angle?: string; hook?: string; estimated_engagement?: string }>
  >([]);

  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deleteAllEpisodesOpen, setDeleteAllEpisodesOpen] = useState(false);
  const [deletingAllEpisodes, setDeletingAllEpisodes] = useState(false);

  // ── Template state ────────────────────────────────────────────────────
  const [savingAsTemplate, setSavingAsTemplate] = useState(false);
  const [saveTemplateSuccess, setSaveTemplateSuccess] = useState(false);
  const [applyTemplateOpen, setApplyTemplateOpen] = useState(false);
  const [availableTemplates, setAvailableTemplates] = useState<
    Array<{
      id: string;
      name: string;
      description?: string;
      is_default?: boolean;
      caption_style?: string;
      music_mood?: string;
      target_duration_seconds?: number;
    }>
  >([]);
  const [loadingTemplates, setLoadingTemplates] = useState(false);
  const [applyingTemplateId, setApplyingTemplateId] = useState<string | null>(null);

  // ── Data fetching ─────────────────────────────────────────────────────
  const fetchData = useCallback(async () => {
    if (!seriesId) return;
    try {
      const { youtube } = await import('@/lib/api');
      const [s, eps, wfs, ytChannels] = await Promise.all([
        seriesApi.get(seriesId),
        episodesApi.list({ series_id: seriesId }),
        workflowsApi.list().catch(() => [] as ComfyUIWorkflow[]),
        youtube.listChannels().catch(() => [] as Array<{ id: string; channel_name: string }>),
      ]);
      setSeriesData(s);
      setEpisodesList(eps);
      setWorkflows(wfs);
      setEditName(s.name);
      setEditDescription(s.description ?? '');
      setEditDuration(String(s.target_duration_seconds));
      setEditStyle(s.visual_style ?? '');
      setEditCharacter(s.character_description ?? '');
      setEditLanguage(s.default_language ?? 'en-US');
      setEditCaptionStyle(s.caption_style ?? DEFAULT_CAPTION_STYLE);
      setEditMusicEnabled(s.music_enabled);
      setEditMusicMood(s.music_mood ?? 'upbeat');
      setEditMusicVolume(s.music_volume_db);
      setEditSceneMode(s.scene_mode ?? 'image');
      setEditVideoWorkflowId(s.video_comfyui_workflow_id ?? '');
      setEditYoutubeChannelId(s.youtube_channel_id ?? '');
      setYoutubeChannels(ytChannels);
      setEditContentFormat(s.content_format ?? 'shorts');
      setEditTargetMinutes(s.target_duration_minutes ?? 30);
      setEditScenesPerChapter(s.scenes_per_chapter ?? 8);
      setEditVisualConsistency(s.visual_consistency_prompt ?? '');
      setEditAspectRatio(s.aspect_ratio ?? '9:16');
      const sUnknown = s as unknown as Record<string, unknown>;
      const tp = (sUnknown.tone_profile as Record<string, unknown> | null | undefined) ?? {};
      setEditTonePersona(typeof tp.persona === 'string' ? tp.persona : '');
      setEditToneForbidden(
        Array.isArray(tp.forbidden_words) ? (tp.forbidden_words as string[]).join(', ') : '',
      );
      setEditToneRequiredMoves(
        Array.isArray(tp.required_moves) ? (tp.required_moves as string[]).join('\n') : '',
      );
      setEditToneReadingLevel(typeof tp.reading_level === 'number' ? tp.reading_level : 8);
      setEditToneMaxSentence(typeof tp.max_sentence_words === 'number' ? tp.max_sentence_words : 18);
      setEditToneStyleSample(typeof tp.style_sample === 'string' ? tp.style_sample : '');
      setEditToneSignaturePhrases(
        Array.isArray(tp.signature_phrases)
          ? (tp.signature_phrases as string[]).join(', ')
          : '',
      );
      setEditToneAllowListicle(Boolean(tp.allow_listicle));
      setEditToneCtaBoilerplate(Boolean(tp.cta_boilerplate));
      const cLock = (sUnknown.character_lock as
        | { asset_ids?: string[]; strength?: number; lora?: string }
        | null
        | undefined) ?? null;
      const sLock = (sUnknown.style_lock as
        | { asset_ids?: string[]; strength?: number; lora?: string }
        | null
        | undefined) ?? null;
      setEditCharacterAssetIds((cLock?.asset_ids ?? []).join(', '));
      setEditCharacterStrength(Number(cLock?.strength ?? 0.75));
      setEditCharacterLora(cLock?.lora ?? '');
      setEditStyleAssetIds((sLock?.asset_ids ?? []).join(', '));
      setEditStyleStrength(Number(sLock?.strength ?? 0.5));
      setEditStyleLora(sLock?.lora ?? '');
      // Mark baseline so the next tick's useEffect doesn't fire an
      // autosave just because we rehydrated state from the server.
      hasLoadedOnce.current = true;
    } catch (err) {
      toast.error('Failed to load series', { description: String(err) });
    } finally {
      setLoading(false);
    }
  }, [seriesId, toast]);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  // Re-fetch YouTube channels when the tab regains focus (e.g. after OAuth redirect)
  useEffect(() => {
    const onFocus = async () => {
      try {
        const { youtube } = await import('@/lib/api');
        const chs = await youtube.listChannels();
        setYoutubeChannels(chs);
      } catch { /* ignore */ }
    };
    const onVisibility = () => {
      if (document.visibilityState === 'visible') void onFocus();
    };
    window.addEventListener('focus', () => void onFocus());
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      window.removeEventListener('focus', () => void onFocus());
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, []);

  // ── Autosave payload builder ──────────────────────────────────────────
  // Kept as a pure builder so deps are explicit. Used by both the
  // debounced autosave and any direct persistence call (e.g. template apply).
  const buildPayload = useCallback(
    () => ({
      name: editName.trim() || undefined,
      description: editDescription.trim() || undefined,
      target_duration_seconds: Number(editDuration) as 15 | 30 | 60,
      visual_style: editStyle || undefined,
      character_description: editCharacter || undefined,
      default_language: editLanguage || undefined,
      caption_style: editCaptionStyle,
      scene_mode: editSceneMode,
      music_enabled: editMusicEnabled,
      music_mood: editMusicMood || undefined,
      music_volume_db: editMusicVolume,
      video_comfyui_workflow_id: editVideoWorkflowId || undefined,
      youtube_channel_id: editYoutubeChannelId || undefined,
      content_format: editContentFormat,
      target_duration_minutes:
        editContentFormat === 'longform' ? editTargetMinutes : undefined,
      scenes_per_chapter:
        editContentFormat === 'longform' ? editScenesPerChapter : undefined,
      visual_consistency_prompt: editVisualConsistency || undefined,
      aspect_ratio: editAspectRatio,
      tone_profile: {
        persona: editTonePersona.trim(),
        forbidden_words: editToneForbidden
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean),
        required_moves: editToneRequiredMoves
          .split('\n')
          .map((s) => s.trim())
          .filter(Boolean),
        reading_level: Number.isFinite(editToneReadingLevel) ? editToneReadingLevel : 8,
        max_sentence_words: Number.isFinite(editToneMaxSentence) ? editToneMaxSentence : 18,
        style_sample: editToneStyleSample.trim() || null,
        signature_phrases: editToneSignaturePhrases
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean),
        allow_listicle: editToneAllowListicle,
        cta_boilerplate: editToneCtaBoilerplate,
      },
      character_lock: editCharacterAssetIds.trim()
        ? {
            asset_ids: editCharacterAssetIds
              .split(',')
              .map((s) => s.trim())
              .filter(Boolean),
            strength: editCharacterStrength,
            lora: editCharacterLora || null,
          }
        : null,
      style_lock: editStyleAssetIds.trim()
        ? {
            asset_ids: editStyleAssetIds
              .split(',')
              .map((s) => s.trim())
              .filter(Boolean),
            strength: editStyleStrength,
            lora: editStyleLora || null,
          }
        : null,
    }),
    [
      editName,
      editDescription,
      editDuration,
      editStyle,
      editCharacter,
      editLanguage,
      editCaptionStyle,
      editSceneMode,
      editMusicEnabled,
      editMusicMood,
      editMusicVolume,
      editVideoWorkflowId,
      editYoutubeChannelId,
      editContentFormat,
      editTargetMinutes,
      editScenesPerChapter,
      editVisualConsistency,
      editAspectRatio,
      editTonePersona,
      editToneForbidden,
      editToneRequiredMoves,
      editToneReadingLevel,
      editToneMaxSentence,
      editToneStyleSample,
      editToneSignaturePhrases,
      editToneAllowListicle,
      editToneCtaBoilerplate,
      editCharacterAssetIds,
      editCharacterStrength,
      editCharacterLora,
      editStyleAssetIds,
      editStyleStrength,
      editStyleLora,
    ],
  );

  // Debounced autosave. Fires ~600ms after the last edit. The signature
  // hash keeps us from spamming saves when unrelated state (toasts,
  // dialog open flags) triggers a re-render.
  const payload = useMemo(() => buildPayload(), [buildPayload]);
  const signature = useMemo(() => JSON.stringify(payload), [payload]);

  useEffect(() => {
    if (!seriesId || !hasLoadedOnce.current) return;
    if (savedSignatureRef.current === '') {
      // First pass after load — seed the baseline, no save.
      savedSignatureRef.current = signature;
      return;
    }
    if (savedSignatureRef.current === signature) return;

    const timer = setTimeout(async () => {
      setAutosaveStatus('saving');
      try {
        await seriesApi.update(seriesId, payload as Parameters<typeof seriesApi.update>[1]);
        savedSignatureRef.current = signature;
        setAutosaveStatus('saved');
        setTimeout(() => {
          setAutosaveStatus((cur) => (cur === 'saved' ? 'idle' : cur));
        }, 1500);
      } catch (err) {
        setAutosaveStatus('error');
        toast.error('Autosave failed', { description: String(err) });
      }
    }, 600);

    return () => clearTimeout(timer);
  }, [signature, payload, seriesId, toast]);

  // ── Handlers ──────────────────────────────────────────────────────────
  const handleDelete = async () => {
    if (!seriesId) return;
    setDeleting(true);
    try {
      await seriesApi.delete(seriesId);
      navigate('/series');
    } catch (err) {
      toast.error('Failed to delete series', { description: String(err) });
      setDeleting(false);
    }
  };

  const handleCreateEpisode = async () => {
    if (!seriesId || !newTitle.trim()) return;
    setCreatingEpisode(true);
    try {
      const ep = await episodesApi.create({
        series_id: seriesId,
        title: newTitle.trim(),
        topic: newTopic.trim() || undefined,
      } as EpisodeCreate);
      setCreateDialogOpen(false);
      setNewTitle('');
      setNewTopic('');
      toast.success('Episode created');
      navigate(`/episodes/${ep.id}`);
    } catch (err) {
      toast.error('Failed to create episode', { description: String(err) });
    } finally {
      setCreatingEpisode(false);
    }
  };

  const handleGenerateAllDrafts = async () => {
    const drafts = episodesList.filter((ep) => ep.status === 'draft');
    if (drafts.length === 0) return;
    setGeneratingAllDrafts(true);
    try {
      await Promise.all(drafts.map((ep) => episodesApi.generate(ep.id)));
      toast.success('Generation started', {
        description: `${drafts.length} draft episode${drafts.length !== 1 ? 's' : ''} queued`,
      });
      void fetchData();
    } catch (err) {
      toast.error('Failed to start generation', { description: String(err) });
    } finally {
      setGeneratingAllDrafts(false);
    }
  };

  const handleAddEpisodesAi = async () => {
    if (!seriesId) return;
    setAddingEpisodesAi(true);
    try {
      await seriesApi.addEpisodesAi(seriesId, 5);
      toast.success('AI episodes added', { description: '5 new episode ideas generated' });
      void fetchData();
    } catch (err) {
      toast.error('Failed to add AI episodes', { description: String(err) });
    } finally {
      setAddingEpisodesAi(false);
    }
  };

  const handleTrendingTopics = async () => {
    if (!seriesId) return;
    setTrendingLoading(true);
    try {
      const result = await seriesApi.trendingTopics(seriesId);
      setTrendingTopics(result.topics || []);
      setTrendingOpen(true);
    } catch (err) {
      toast.error('Failed to fetch trending topics', { description: String(err) });
    } finally {
      setTrendingLoading(false);
    }
  };

  const handleSaveAsTemplate = async () => {
    if (!seriesId) return;
    setSavingAsTemplate(true);
    setSaveTemplateSuccess(false);
    try {
      await videoTemplatesApi.fromSeries(seriesId);
      setSaveTemplateSuccess(true);
      toast.success('Template saved', {
        description: 'Current series settings saved as a reusable template',
      });
      setTimeout(() => setSaveTemplateSuccess(false), 3000);
    } catch (err) {
      toast.error('Failed to save template', { description: String(err) });
    } finally {
      setSavingAsTemplate(false);
    }
  };

  const openApplyTemplateDialog = async () => {
    setApplyTemplateOpen(true);
    setLoadingTemplates(true);
    try {
      const tmpl = await videoTemplatesApi.list();
      setAvailableTemplates(tmpl);
    } catch (err) {
      toast.error('Failed to load templates', { description: String(err) });
      setAvailableTemplates([]);
    } finally {
      setLoadingTemplates(false);
    }
  };

  const handleApplyTemplate = async (templateId: string) => {
    if (!seriesId) return;
    setApplyingTemplateId(templateId);
    try {
      await videoTemplatesApi.applyToSeries(templateId, seriesId);
      toast.success('Template applied', { description: 'Series settings updated from template' });
      setApplyTemplateOpen(false);
      void fetchData();
    } catch (err) {
      toast.error('Failed to apply template', { description: String(err) });
    } finally {
      setApplyingTemplateId(null);
    }
  };

  // ── Loading / not-found guards ────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <Spinner size="lg" />
      </div>
    );
  }

  if (!seriesData) {
    return (
      <div className="text-center py-20">
        <p className="text-txt-secondary">Series not found</p>
        <Button variant="ghost" className="mt-4" onClick={() => navigate('/series')}>
          <ArrowLeft size={14} />
          Back to Series
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Breadcrumb + autosave status pill */}
      <div className="flex items-center justify-between gap-4">
        <Breadcrumb
          items={[
            { label: 'Series', to: '/series' },
            { label: editName || seriesData.name || 'Series Detail' },
          ]}
        />
        <AutosaveStatusPill status={autosaveStatus} />
      </div>

      {/* Hero card — always visible above the tabs */}
      <HeroCard
        name={editName}
        onNameChange={setEditName}
        description={editDescription}
        onDescriptionChange={setEditDescription}
        episodeCount={episodesList.length}
        totalRuntimeSeconds={episodesList.length * seriesData.target_duration_seconds}
        language={seriesData.default_language ?? editLanguage}
        contentFormat={editContentFormat}
        lastActivity={
          episodesList.length > 0
            ? episodesList
                .map((ep) => ep.updated_at)
                .sort()
                .reverse()[0] ?? null
            : null
        }
        onApplyTemplate={() => void openApplyTemplateDialog()}
        onSaveAsTemplate={() => void handleSaveAsTemplate()}
        savingAsTemplate={savingAsTemplate}
        saveTemplateSuccess={saveTemplateSuccess}
        onDelete={() => setDeleteDialogOpen(true)}
      />

      {/* ── Tab bar ──────────────────────────────────────────────────── */}
      {/* On md and below: horizontally scrollable row so all tabs stay
          visible without a dropdown — keeps the user oriented. */}
      <div
        className="flex overflow-x-auto scrollbar-none border-b border-border -mx-1 px-1"
        role="tablist"
        aria-label="Series sections"
      >
        {TABS.map(({ id, label, icon: Icon }) => {
          const active = activeTab === id;
          return (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={active}
              aria-controls={`tabpanel-${id}`}
              onClick={() => handleTabChange(id)}
              className={[
                'flex items-center gap-2 px-4 py-2.5 text-sm font-medium whitespace-nowrap border-b-2 transition-colors duration-fast shrink-0',
                active
                  ? 'border-accent text-accent'
                  : 'border-transparent text-txt-secondary hover:text-txt-primary hover:border-border',
              ].join(' ')}
            >
              <Icon size={15} className="shrink-0" />
              {label}
            </button>
          );
        })}
      </div>

      {/* ── Tab panels ───────────────────────────────────────────────── */}
      <div
        id="tabpanel-episodes"
        role="tabpanel"
        aria-labelledby="tab-episodes"
        hidden={activeTab !== 'episodes'}
      >
        {activeTab === 'episodes' && (
          <EpisodesTab
            episodes={episodesList}
            onCreate={() => setCreateDialogOpen(true)}
            onGenerateAllDrafts={() => void handleGenerateAllDrafts()}
            onAiAdd={() => void handleAddEpisodesAi()}
            onTrending={() => void handleTrendingTopics()}
            onDeleteAll={() => setDeleteAllEpisodesOpen(true)}
            generatingAllDrafts={generatingAllDrafts}
            addingEpisodesAi={addingEpisodesAi}
            trendingLoading={trendingLoading}
          />
        )}
      </div>

      <div
        id="tabpanel-setup"
        role="tabpanel"
        aria-labelledby="tab-setup"
        hidden={activeTab !== 'setup'}
      >
        {activeTab === 'setup' && (
          <SetupTab
            // Voice & language
            editDuration={editDuration}
            onDurationChange={setEditDuration}
            editLanguage={editLanguage}
            onLanguageChange={setEditLanguage}
            editCharacter={editCharacter}
            onCharacterChange={setEditCharacter}
            editCaptionStyle={editCaptionStyle}
            onCaptionStyleChange={setEditCaptionStyle}
            // Visual
            editStyle={editStyle}
            onStyleChange={setEditStyle}
            // Music
            editMusicEnabled={editMusicEnabled}
            onMusicEnabledChange={setEditMusicEnabled}
            editMusicMood={editMusicMood}
            onMusicMoodChange={setEditMusicMood}
            editMusicVolume={editMusicVolume}
            onMusicVolumeChange={setEditMusicVolume}
            // Publish
            editYoutubeChannelId={editYoutubeChannelId}
            onYoutubeChannelIdChange={setEditYoutubeChannelId}
            youtubeChannels={youtubeChannels}
            // Pipeline
            editContentFormat={editContentFormat}
            onContentFormatChange={setEditContentFormat}
            editAspectRatio={editAspectRatio}
            onAspectRatioChange={setEditAspectRatio}
            editTargetMinutes={editTargetMinutes}
            onTargetMinutesChange={setEditTargetMinutes}
            editScenesPerChapter={editScenesPerChapter}
            onScenesPerChapterChange={setEditScenesPerChapter}
            editVisualConsistency={editVisualConsistency}
            onVisualConsistencyChange={setEditVisualConsistency}
            editSceneMode={editSceneMode}
            onSceneModeChange={setEditSceneMode}
            editVideoWorkflowId={editVideoWorkflowId}
            onVideoWorkflowIdChange={setEditVideoWorkflowId}
            workflows={workflows}
            // Tone profile
            editTonePersona={editTonePersona}
            onTonePersonaChange={setEditTonePersona}
            editToneForbidden={editToneForbidden}
            onToneForbiddenChange={setEditToneForbidden}
            editToneRequiredMoves={editToneRequiredMoves}
            onToneRequiredMovesChange={setEditToneRequiredMoves}
            editToneReadingLevel={editToneReadingLevel}
            onToneReadingLevelChange={setEditToneReadingLevel}
            editToneMaxSentence={editToneMaxSentence}
            onToneMaxSentenceChange={setEditToneMaxSentence}
            editToneStyleSample={editToneStyleSample}
            onToneStyleSampleChange={setEditToneStyleSample}
            editToneSignaturePhrases={editToneSignaturePhrases}
            onToneSignaturePhrasesChange={setEditToneSignaturePhrases}
            editToneAllowListicle={editToneAllowListicle}
            onToneAllowListicleChange={setEditToneAllowListicle}
            editToneCtaBoilerplate={editToneCtaBoilerplate}
            onToneCtaBoilerplateChange={setEditToneCtaBoilerplate}
            // Asset locks
            editCharacterAssetIds={editCharacterAssetIds}
            onCharacterAssetIdsChange={setEditCharacterAssetIds}
            editCharacterStrength={editCharacterStrength}
            onCharacterStrengthChange={setEditCharacterStrength}
            editCharacterLora={editCharacterLora}
            onCharacterLoraChange={setEditCharacterLora}
            editStyleAssetIds={editStyleAssetIds}
            onStyleAssetIdsChange={setEditStyleAssetIds}
            editStyleStrength={editStyleStrength}
            onStyleStrengthChange={setEditStyleStrength}
            editStyleLora={editStyleLora}
            onStyleLoraChange={setEditStyleLora}
          />
        )}
      </div>

      <div
        id="tabpanel-analytics"
        role="tabpanel"
        aria-labelledby="tab-analytics"
        hidden={activeTab !== 'analytics'}
      >
        {activeTab === 'analytics' && seriesId && (
          <AnalyticsTab seriesId={seriesId} />
        )}
      </div>

      {/* ── Dialogs ──────────────────────────────────────────────────── */}

      {/* Create Episode */}
      <Dialog
        open={createDialogOpen}
        onClose={() => setCreateDialogOpen(false)}
        title="Create New Episode"
        description={`Add a new episode to "${seriesData.name}"`}
      >
        <div className="space-y-4">
          <Input
            label="Title"
            placeholder="Episode title..."
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            autoFocus
          />
          <Textarea
            label="Topic"
            placeholder="What should this episode be about?"
            value={newTopic}
            onChange={(e) => setNewTopic(e.target.value)}
          />
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setCreateDialogOpen(false)}>
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={creatingEpisode}
            disabled={!newTitle.trim()}
            onClick={() => void handleCreateEpisode()}
          >
            Create Episode
          </Button>
        </DialogFooter>
      </Dialog>

      {/* Delete Series */}
      <Dialog
        open={deleteDialogOpen}
        onClose={() => setDeleteDialogOpen(false)}
        title="Delete Series"
        description="This will permanently delete the series and all its episodes. This action cannot be undone."
      >
        <DialogFooter>
          <Button variant="ghost" onClick={() => setDeleteDialogOpen(false)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            loading={deleting}
            onClick={() => void handleDelete()}
          >
            <Trash2 size={14} />
            Delete Series
          </Button>
        </DialogFooter>
      </Dialog>

      {/* Delete All Episodes */}
      <Dialog
        open={deleteAllEpisodesOpen}
        onClose={() => setDeleteAllEpisodesOpen(false)}
        title="Delete All Episodes"
        description={`Delete all ${episodesList.length} episodes from this series? This removes all generated media. The series itself will be kept.`}
      >
        <DialogFooter>
          <Button variant="ghost" onClick={() => setDeleteAllEpisodesOpen(false)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            loading={deletingAllEpisodes}
            onClick={async () => {
              setDeletingAllEpisodes(true);
              try {
                await Promise.all(episodesList.map((ep) => episodesApi.delete(ep.id)));
                toast.success('All episodes deleted');
                setDeleteAllEpisodesOpen(false);
                void fetchData();
              } catch (err) {
                toast.error('Failed to delete all episodes', { description: String(err) });
              } finally {
                setDeletingAllEpisodes(false);
              }
            }}
          >
            <Trash2 size={14} />
            Delete All ({episodesList.length})
          </Button>
        </DialogFooter>
      </Dialog>

      {/* Apply Template */}
      <Dialog
        open={applyTemplateOpen}
        onClose={() => setApplyTemplateOpen(false)}
        title="Apply Template"
        description="Select a template to apply its settings to this series. Your current settings will be replaced."
      >
        <div
          className="space-y-3 max-h-[420px] overflow-y-auto"
          aria-busy={loadingTemplates}
          aria-live="polite"
        >
          {loadingTemplates && (
            <div className="flex items-center justify-center py-10">
              <Spinner />
            </div>
          )}
          {!loadingTemplates && availableTemplates.length === 0 && (
            <div className="text-center py-8">
              <LayoutTemplate size={28} className="mx-auto text-txt-tertiary mb-2" />
              <p className="text-sm text-txt-secondary">No templates found.</p>
              <p className="text-xs text-txt-tertiary mt-1">
                Create templates in Settings &rarr; Templates.
              </p>
            </div>
          )}
          {!loadingTemplates &&
            availableTemplates.map((tmpl) => (
              <button
                key={tmpl.id}
                type="button"
                disabled={applyingTemplateId !== null}
                onClick={() => void handleApplyTemplate(tmpl.id)}
                className="w-full text-left rounded-lg border border-border bg-bg-elevated hover:bg-bg-hover hover:border-accent/40 transition-colors duration-fast p-3 space-y-2 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-1 focus:ring-offset-bg-base"
                aria-label={`Apply template ${tmpl.name}`}
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <LayoutTemplate size={13} className="text-accent shrink-0" />
                    <span className="text-sm font-semibold text-txt-primary truncate">
                      {tmpl.name}
                    </span>
                    {tmpl.is_default && (
                      <Badge variant="accent" className="text-[9px] shrink-0">
                        Default
                      </Badge>
                    )}
                  </div>
                  {applyingTemplateId === tmpl.id && <Spinner size="sm" />}
                </div>
                {tmpl.description && (
                  <p className="text-xs text-txt-secondary line-clamp-2">{tmpl.description}</p>
                )}
                <div className="flex flex-wrap gap-1">
                  {tmpl.caption_style && (
                    <span className="px-1.5 py-0.5 rounded bg-accent/10 text-accent text-[10px] font-medium">
                      {tmpl.caption_style}
                    </span>
                  )}
                  {tmpl.music_mood && (
                    <span className="px-1.5 py-0.5 rounded bg-bg-active text-txt-secondary text-[10px]">
                      {tmpl.music_mood}
                    </span>
                  )}
                  {tmpl.target_duration_seconds && (
                    <span className="px-1.5 py-0.5 rounded bg-bg-active text-txt-secondary text-[10px]">
                      {tmpl.target_duration_seconds}s
                    </span>
                  )}
                </div>
              </button>
            ))}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setApplyTemplateOpen(false)}>
            Close
          </Button>
        </DialogFooter>
      </Dialog>

      {/* Trending Topics */}
      <Dialog
        open={trendingOpen}
        onClose={() => setTrendingOpen(false)}
        title="Trending Topic Ideas"
      >
        <div className="space-y-3 max-h-[400px] overflow-y-auto">
          {trendingTopics.length === 0 ? (
            <p className="text-sm text-txt-secondary text-center py-6">
              No topic ideas returned.
            </p>
          ) : (
            trendingTopics.map((t, i) => (
              <Card key={i} padding="sm" className="space-y-1">
                <p className="text-sm font-semibold text-txt-primary">{t.title}</p>
                {t.angle && (
                  <p className="text-xs text-txt-secondary">{t.angle}</p>
                )}
                {t.hook && (
                  <p className="text-xs text-accent italic">Hook: &quot;{t.hook}&quot;</p>
                )}
                {t.estimated_engagement && (
                  <Badge
                    variant={
                      t.estimated_engagement === 'high'
                        ? 'success'
                        : t.estimated_engagement === 'medium'
                          ? 'warning'
                          : 'neutral'
                    }
                  >
                    {t.estimated_engagement} engagement
                  </Badge>
                )}
              </Card>
            ))
          )}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setTrendingOpen(false)}>
            Close
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}

export default SeriesDetail;
