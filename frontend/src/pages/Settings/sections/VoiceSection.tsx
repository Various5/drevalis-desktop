import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Mic2,
  Plus,
  Trash2,
  Volume2,
  Play,
  Pause,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Card } from '@/components/ui/Card';
import { EmptyState } from '@/components/ui/EmptyState';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { Badge } from '@/components/ui/Badge';
import { Dialog, DialogFooter } from '@/components/ui/Dialog';
import { Spinner } from '@/components/ui/Spinner';
import { useToast } from '@/components/ui/Toast';
import { voiceProfiles, assets as apiAssets } from '@/lib/api';
import type { VoiceProfile } from '@/types';

// ---------------------------------------------------------------------------
// Types / Constants
// ---------------------------------------------------------------------------

type ProviderFilter = 'all' | 'edge' | 'piper' | 'kokoro' | 'elevenlabs' | 'comfyui_elevenlabs';
type ProviderOption = 'piper' | 'elevenlabs' | 'kokoro' | 'edge' | 'comfyui_elevenlabs';

// ComfyUI ElevenLabs preset voices — names stay English (these are the
// upstream voice display names as ElevenLabs ships them).
const COMFYUI_ELEVENLABS_VOICES: Array<{ value: string; label: string }> = [
  { value: 'Roger (male, american)', label: 'Roger (male, american)' },
  { value: 'Sarah (female, american)', label: 'Sarah (female, american)' },
  { value: 'Laura (female, american)', label: 'Laura (female, american)' },
  { value: 'Charlie (male, australian)', label: 'Charlie (male, australian)' },
  { value: 'George (male, british)', label: 'George (male, british)' },
  { value: 'Callum (male, american)', label: 'Callum (male, american)' },
  { value: 'River (neutral, american)', label: 'River (neutral, american)' },
  { value: 'Harry (male, american)', label: 'Harry (male, american)' },
  { value: 'Liam (male, american)', label: 'Liam (male, american)' },
  { value: 'Alice (female, british)', label: 'Alice (female, british)' },
  { value: 'Matilda (female, american)', label: 'Matilda (female, american)' },
  { value: 'Will (male, american)', label: 'Will (male, american)' },
  { value: 'Jessica (female, american)', label: 'Jessica (female, american)' },
  { value: 'Eric (male, american)', label: 'Eric (male, american)' },
  { value: 'Bella (female, american)', label: 'Bella (female, american)' },
  { value: 'Chris (male, american)', label: 'Chris (male, american)' },
  { value: 'Brian (male, american)', label: 'Brian (male, american)' },
  { value: 'Daniel (male, british)', label: 'Daniel (male, british)' },
  { value: 'Lily (female, british)', label: 'Lily (female, british)' },
  { value: 'Adam (male, american)', label: 'Adam (male, american)' },
  { value: 'Bill (male, american)', label: 'Bill (male, american)' },
];

// ---------------------------------------------------------------------------
// RecordingTimer
// ---------------------------------------------------------------------------

function RecordingTimer({ startedAt }: { startedAt: number }) {
  const { t } = useTranslation();
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(timer);
  }, []);
  const s = Math.floor((now - startedAt) / 1000);
  return <span className="text-xs font-mono text-error">● {t('settings.voice.clone.secondsSuffix', { count: s })}</span>;
}

// ---------------------------------------------------------------------------
// VoiceCloneDialog
// ---------------------------------------------------------------------------

function VoiceCloneDialog({
  onClose,
  onDone,
}: {
  onClose: () => void;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const [assets, setAssetsList] = useState<Array<{ id: string; filename: string; duration_seconds: number | null }>>([]);
  const [displayName, setDisplayName] = useState('');
  const [selectedAssetId, setSelectedAssetId] = useState('');
  const [provider, setProvider] = useState<'elevenlabs' | 'piper' | 'kokoro'>('elevenlabs');
  const [busy, setBusy] = useState(false);

  // Mic recording state
  const [recording, setRecording] = useState(false);
  const [recordedBlob, setRecordedBlob] = useState<Blob | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [recStart, setRecStart] = useState<number | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const mediaChunksRef = useRef<BlobPart[]>([]);

  useEffect(() => {
    void apiAssets.list({ kind: 'audio' }).then((rows) =>
      setAssetsList(
        rows.map((a) => ({
          id: a.id,
          filename: a.filename,
          duration_seconds: a.duration_seconds,
        })),
      ),
    );
  }, []);

  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream, { mimeType: 'audio/webm' });
      mediaChunksRef.current = [];
      mr.ondataavailable = (e) => {
        if (e.data.size > 0) mediaChunksRef.current.push(e.data);
      };
      mr.onstop = () => {
        const blob = new Blob(mediaChunksRef.current, { type: 'audio/webm' });
        setRecordedBlob(blob);
        setPreviewUrl(URL.createObjectURL(blob));
        stream.getTracks().forEach((tr) => tr.stop());
      };
      mr.start();
      mediaRecorderRef.current = mr;
      setRecording(true);
      setRecStart(Date.now());
    } catch {
      toast.error(t('settings.voice.clone.micDenied'), {
        description: t('settings.voice.clone.micDeniedDesc'),
      });
    }
  };

  const stopRecording = () => {
    mediaRecorderRef.current?.stop();
    setRecording(false);
    setRecStart(null);
  };

  const uploadRecording = async (): Promise<string | null> => {
    if (!recordedBlob) return null;
    try {
      const file = new File([recordedBlob], `voice-sample-${Date.now()}.webm`, {
        type: 'audio/webm',
      });
      const a = await apiAssets.upload(file, { tags: ['voice-sample'] });
      return a.id;
    } catch (err) {
      toast.error(t('settings.voice.clone.uploadFailed'), { description: String(err) });
      return null;
    }
  };

  const submit = async () => {
    if (!displayName.trim()) {
      toast.error(t('settings.voice.clone.nameRequired'));
      return;
    }
    let assetId = selectedAssetId;
    if (!assetId && recordedBlob) {
      const id = await uploadRecording();
      if (!id) return;
      assetId = id;
    }
    if (!assetId) {
      toast.error(t('settings.voice.clone.samplePickRequired'));
      return;
    }
    setBusy(true);
    try {
      const res = await voiceProfiles.clone({
        asset_id: assetId,
        display_name: displayName.trim(),
        provider,
      });
      toast.success(t('settings.voice.clone.createdToast'), {
        description: res.note,
      });
      onDone();
    } catch (err) {
      toast.error(t('settings.voice.clone.cloneFailed'), { description: String(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onClose={onClose} title={t('settings.voice.clone.title')}>
      <div className="space-y-3">
        <p className="text-xs text-txt-secondary">
          {t('settings.voice.clone.intro')}
        </p>

        {/* Mic capture */}
        <div className="p-3 rounded border border-white/[0.06] bg-bg-elevated space-y-2">
          <div className="flex items-center justify-between">
            <div className="text-xs font-medium text-txt-primary">{t('settings.voice.clone.browserMic')}</div>
            {recording && recStart && (
              <RecordingTimer startedAt={recStart} />
            )}
          </div>
          <div className="flex gap-2">
            {!recording ? (
              <Button
                variant="primary"
                size="sm"
                onClick={() => void startRecording()}
                disabled={!!recordedBlob}
              >
                {recordedBlob ? t('settings.voice.clone.recorded') : t('settings.voice.clone.record')}
              </Button>
            ) : (
              <Button variant="ghost" size="sm" onClick={stopRecording}>
                {t('settings.voice.clone.stop')}
              </Button>
            )}
            {recordedBlob && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setRecordedBlob(null);
                  if (previewUrl) URL.revokeObjectURL(previewUrl);
                  setPreviewUrl(null);
                }}
              >
                {t('settings.voice.clone.discard')}
              </Button>
            )}
          </div>
          {previewUrl && (
            <audio src={previewUrl} controls className="w-full h-8" />
          )}
          <div className="text-[10px] text-txt-muted">
            {t('settings.voice.clone.tip')}
          </div>
        </div>
        <div className="text-[11px] text-txt-muted text-center">{t('settings.voice.clone.or')}</div>
        <label className="block text-xs">
          <span className="text-txt-secondary mb-1 block">{t('settings.voice.clone.displayName')}</span>
          <Input
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder={t('settings.voice.clone.displayNamePlaceholder')}
          />
        </label>
        <label className="block text-xs">
          <span className="text-txt-secondary mb-1 block">{t('settings.voice.clone.sampleLabel')}</span>
          <select
            value={selectedAssetId}
            onChange={(e) => setSelectedAssetId(e.target.value)}
            className="w-full px-3 py-2 bg-bg-base border border-white/[0.08] rounded-md text-sm text-txt-primary"
          >
            <option value="">{t('settings.voice.clone.selectAssetPlaceholder')}</option>
            {assets.map((a) => (
              <option key={a.id} value={a.id}>
                {a.filename}
                {a.duration_seconds
                  ? ' ' + t('settings.voice.clone.assetDurationSuffix', { seconds: Math.round(a.duration_seconds) })
                  : ''}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-xs">
          <span className="text-txt-secondary mb-1 block">{t('settings.voice.clone.providerLabel')}</span>
          <select
            value={provider}
            onChange={(e) => setProvider(e.target.value as 'elevenlabs' | 'piper' | 'kokoro')}
            className="w-full px-3 py-2 bg-bg-base border border-white/[0.08] rounded-md text-sm text-txt-primary"
          >
            <option value="elevenlabs">{t('settings.voice.clone.providerOptions.elevenlabs')}</option>
            <option value="piper">{t('settings.voice.clone.providerOptions.piper')}</option>
            <option value="kokoro">{t('settings.voice.clone.providerOptions.kokoro')}</option>
          </select>
        </label>
      </div>
      <DialogFooter>
        <Button variant="ghost" onClick={onClose}>
          {t('settings.voice.clone.cancel')}
        </Button>
        <Button variant="primary" onClick={() => void submit()} disabled={busy}>
          {busy ? t('settings.voice.clone.cloning') : t('settings.voice.clone.submit')}
        </Button>
      </DialogFooter>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// VoiceSection
// ---------------------------------------------------------------------------

export function VoiceSection() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const [profiles, setProfiles] = useState<VoiceProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [cloneOpen, setCloneOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  const [filter, setFilter] = useState<ProviderFilter>('all');
  const [playingId, setPlayingId] = useState<string | null>(null);

  // Form
  const [formName, setFormName] = useState('');
  const [formProvider, setFormProvider] = useState<ProviderOption>('edge');
  const [formPiperModel, setFormPiperModel] = useState('');
  const [formElevenLabsId, setFormElevenLabsId] = useState('');
  const [formKokoroVoiceName, setFormKokoroVoiceName] = useState('');
  const [formKokoroModelPath, setFormKokoroModelPath] = useState('');
  const [formEdgeVoiceId, setFormEdgeVoiceId] = useState('');
  const [formSpeed, setFormSpeed] = useState('1.0');

  const providerOptions: Array<{ value: ProviderOption; label: string }> = [
    { value: 'edge', label: t('settings.voice.providerOptions.edge') },
    { value: 'piper', label: t('settings.voice.providerOptions.piper') },
    { value: 'kokoro', label: t('settings.voice.providerOptions.kokoro') },
    { value: 'elevenlabs', label: t('settings.voice.providerOptions.elevenlabs') },
    { value: 'comfyui_elevenlabs', label: t('settings.voice.providerOptions.comfyui_elevenlabs') },
  ];

  // Filter tabs — brand names stay constant; only "All" is translated.
  const filterTabs: Array<{ value: ProviderFilter; label: string }> = [
    { value: 'all', label: t('settings.voice.filters.all') },
    { value: 'edge', label: 'Edge' },
    { value: 'piper', label: 'Piper' },
    { value: 'kokoro', label: 'Kokoro' },
    { value: 'elevenlabs', label: 'ElevenLabs' },
    { value: 'comfyui_elevenlabs', label: 'ComfyUI 11L' },
  ];

  const fetchProfiles = useCallback(async () => {
    try {
      const res = await voiceProfiles.list();
      setProfiles(res);
    } catch (err) {
      toast.error(t('settings.voice.loadFailed'), { description: String(err) });
    } finally {
      setLoading(false);
    }
  }, [toast, t]);

  useEffect(() => {
    void fetchProfiles();
  }, [fetchProfiles]);

  const handleCreate = async () => {
    setCreating(true);
    try {
      // Auto-detect gender from ComfyUI ElevenLabs voice name
      let gender: string | undefined;
      if (formProvider === 'comfyui_elevenlabs' && formElevenLabsId) {
        if (formElevenLabsId.includes('female')) gender = 'female';
        else if (formElevenLabsId.includes('male')) gender = 'male';
      }

      await voiceProfiles.create({
        name: formName.trim(),
        provider: formProvider,
        speed: parseFloat(formSpeed) || 1.0,
        piper_model_path: formProvider === 'piper' ? formPiperModel.trim() || undefined : undefined,
        elevenlabs_voice_id: (formProvider === 'elevenlabs' || formProvider === 'comfyui_elevenlabs') ? formElevenLabsId.trim() || undefined : undefined,
        kokoro_voice_name: formProvider === 'kokoro' ? formKokoroVoiceName.trim() || undefined : undefined,
        kokoro_model_path: formProvider === 'kokoro' ? formKokoroModelPath.trim() || undefined : undefined,
        edge_voice_id: formProvider === 'edge' ? formEdgeVoiceId.trim() || undefined : undefined,
        gender,
      });
      toast.success(t('settings.voice.addedToast'));
      setDialogOpen(false);
      resetForm();
      void fetchProfiles();
    } catch (err) {
      toast.error(t('settings.voice.addFailed'), { description: String(err) });
    } finally {
      setCreating(false);
    }
  };

  const resetForm = () => {
    setFormName('');
    setFormProvider('edge');
    setFormPiperModel('');
    setFormElevenLabsId('');
    setFormKokoroVoiceName('');
    setFormKokoroModelPath('');
    setFormEdgeVoiceId('');
    setFormSpeed('1.0');
  };

  const handleTest = async (id: string) => {
    setTesting(id);
    try {
      const result = await voiceProfiles.test(id);
      if (result.audio_path) {
        toast.success(t('settings.voice.sampleGenerated'));
        void fetchProfiles();
        let src = result.audio_path;
        const idx = src.indexOf('storage/');
        if (idx >= 0) src = '/' + src.slice(idx);
        else if (!src.startsWith('/')) src = '/' + src;
        const audio = new Audio(src);
        audio.play().catch(() => {
          /* autoplay might be blocked */
        });
      }
    } catch (err) {
      toast.error(t('settings.voice.testFailed'), { description: String(err) });
    } finally {
      setTesting(null);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await voiceProfiles.delete(id);
      toast.success(t('settings.voice.deletedToast'));
      void fetchProfiles();
    } catch (err) {
      toast.error(t('settings.voice.deleteFailed'), { description: String(err) });
    }
  };

  const handlePlayPause = (profileId: string) => {
    document.querySelectorAll('audio').forEach((a) => {
      if (a.id !== `audio-${profileId}`) {
        (a as HTMLAudioElement).pause();
        (a as HTMLAudioElement).currentTime = 0;
      }
    });

    const audio = document.getElementById(`audio-${profileId}`) as HTMLAudioElement | null;
    if (!audio) return;

    if (audio.paused) {
      audio.play().catch(() => {});
      setPlayingId(profileId);

      audio.onended = () => setPlayingId(null);
      audio.onpause = () => {
        if (playingId === profileId) setPlayingId(null);
      };
    } else {
      audio.pause();
      setPlayingId(null);
    }
  };

  const filteredProfiles = filter === 'all'
    ? profiles
    : profiles.filter((p) => p.provider === filter);

  const getProviderBadgeVariant = (provider: string) => {
    switch (provider) {
      case 'edge': return 'info';
      case 'piper': return 'success';
      case 'kokoro': return 'accent';
      case 'elevenlabs': return 'warning';
      default: return 'neutral';
    }
  };

  if (loading) return <Spinner />;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-txt-primary">
          {t('settings.voice.heading')}
        </h3>
        <div className="flex gap-2">
          <Button variant="ghost" size="sm" onClick={() => setCloneOpen(true)}>
            <Mic2 size={14} />
            {t('settings.voice.cloneVoice')}
          </Button>
          <Button variant="primary" size="sm" onClick={() => setDialogOpen(true)}>
            <Plus size={14} />
            {t('settings.voice.addProfile')}
          </Button>
        </div>
      </div>

      {/* Provider filter tabs */}
      <div className="flex items-center gap-1 p-1 bg-bg-elevated rounded-md w-fit">
        {filterTabs.map((tab) => (
          <button
            key={tab.value}
            onClick={() => setFilter(tab.value)}
            className={[
              'px-3 py-1.5 text-xs font-medium rounded transition-colors duration-fast',
              filter === tab.value
                ? 'bg-bg-surface text-txt-primary shadow-sm'
                : 'text-txt-secondary hover:text-txt-primary',
            ].join(' ')}
          >
            {tab.label}
            {tab.value !== 'all' && (
              <span className="ml-1 text-txt-tertiary">
                ({profiles.filter((p) => p.provider === tab.value).length})
              </span>
            )}
          </button>
        ))}
      </div>

      {filteredProfiles.length === 0 ? (
        <EmptyState
          icon={Mic2}
          title={
            filter === 'all'
              ? t('settings.voice.emptyAll')
              : t('settings.voice.emptyFiltered', { provider: filter })
          }
        />
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {filteredProfiles.map((p) => (
            <Card key={p.id} padding="md" className="flex flex-col">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <h4 className="text-sm font-semibold text-txt-primary truncate">
                    {p.name}
                  </h4>
                  <div className="flex items-center gap-1.5 mt-1.5 flex-wrap">
                    <Badge variant={getProviderBadgeVariant(p.provider)} className="text-[10px]">
                      {p.provider}
                    </Badge>
                    <span className="text-[10px] text-txt-tertiary">
                      {t('settings.voice.speedSuffix', { speed: p.speed })}
                    </span>
                    {p.sample_audio_path && p.provider === 'elevenlabs' && !p.elevenlabs_voice_id && (
                      <Badge variant="neutral" className="text-[10px]">
                        {t('settings.voice.clonePendingBadge')}
                      </Badge>
                    )}
                  </div>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => void handleDelete(p.id)}
                  className="shrink-0"
                >
                  <Trash2 size={12} />
                </Button>
              </div>

              <p className="text-[11px] text-txt-tertiary mt-2 truncate">
                {p.piper_model_path && t('settings.voice.modelLabel', { path: p.piper_model_path })}
                {p.elevenlabs_voice_id && t('settings.voice.voiceLabel', { value: p.elevenlabs_voice_id })}
                {p.kokoro_voice_name && t('settings.voice.voiceLabel', { value: p.kokoro_voice_name })}
                {p.edge_voice_id && t('settings.voice.voiceLabel', { value: p.edge_voice_id })}
                {!p.piper_model_path && !p.elevenlabs_voice_id && !p.kokoro_voice_name && !p.edge_voice_id && t('settings.voice.defaultConfig')}
              </p>

              <div className="mt-auto pt-3 flex items-center gap-2">
                {p.sample_audio_path ? (
                  <>
                    <button
                      onClick={() => handlePlayPause(p.id)}
                      className={[
                        'flex items-center gap-1.5 px-2.5 py-1.5 rounded text-xs font-medium transition-colors duration-fast',
                        playingId === p.id
                          ? 'bg-accent text-txt-onAccent'
                          : 'bg-accent-muted text-accent hover:bg-accent/20',
                      ].join(' ')}
                    >
                      {playingId === p.id ? <Pause size={12} /> : <Play size={12} />}
                      {playingId === p.id ? t('settings.voice.pauseButton') : t('settings.voice.previewButton')}
                    </button>
                    <audio
                      id={`audio-${p.id}`}
                      src={`/storage/${p.sample_audio_path}`}
                      preload="none"
                    />
                  </>
                ) : (
                  <Button
                    variant="ghost"
                    size="sm"
                    loading={testing === p.id}
                    onClick={() => void handleTest(p.id)}
                  >
                    <Volume2 size={12} />
                    {t('settings.voice.generateSample')}
                  </Button>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}

      <Dialog
        open={dialogOpen}
        onClose={() => { setDialogOpen(false); resetForm(); }}
        title={t('settings.voice.dialog.title')}
      >
        <div className="space-y-4">
          <Input
            label={t('settings.voice.dialog.nameLabel')}
            value={formName}
            onChange={(e) => setFormName(e.target.value)}
            placeholder={t('settings.voice.dialog.namePlaceholder')}
          />
          <Select
            label={t('settings.voice.dialog.providerLabel')}
            value={formProvider}
            onChange={(e) =>
              setFormProvider(e.target.value as ProviderOption)
            }
            options={providerOptions}
          />
          {formProvider === 'edge' && (
            <Input
              label={t('settings.voice.dialog.edgeVoiceIdLabel')}
              value={formEdgeVoiceId}
              onChange={(e) => setFormEdgeVoiceId(e.target.value)}
              placeholder={t('settings.voice.dialog.edgeVoiceIdPlaceholder')}
              hint={t('settings.voice.dialog.edgeVoiceIdHint')}
            />
          )}
          {formProvider === 'piper' && (
            <Input
              label={t('settings.voice.dialog.piperModelLabel')}
              value={formPiperModel}
              onChange={(e) => setFormPiperModel(e.target.value)}
              placeholder={t('settings.voice.dialog.piperModelPlaceholder')}
            />
          )}
          {formProvider === 'kokoro' && (
            <>
              <Input
                label={t('settings.voice.dialog.kokoroVoiceLabel')}
                value={formKokoroVoiceName}
                onChange={(e) => setFormKokoroVoiceName(e.target.value)}
                placeholder={t('settings.voice.dialog.kokoroVoicePlaceholder')}
              />
              <Input
                label={t('settings.voice.dialog.kokoroModelLabel')}
                value={formKokoroModelPath}
                onChange={(e) => setFormKokoroModelPath(e.target.value)}
                placeholder={t('settings.voice.dialog.kokoroModelPlaceholder')}
              />
            </>
          )}
          {formProvider === 'elevenlabs' && (
            <Input
              label={t('settings.voice.dialog.elevenlabsVoiceIdLabel')}
              value={formElevenLabsId}
              onChange={(e) => setFormElevenLabsId(e.target.value)}
              placeholder={t('settings.voice.dialog.elevenlabsVoiceIdPlaceholder')}
            />
          )}
          {formProvider === 'comfyui_elevenlabs' && (
            <Select
              label={t('settings.voice.dialog.elevenlabsSelectLabel')}
              value={formElevenLabsId}
              placeholder={t('settings.voice.dialog.elevenlabsSelectPlaceholder')}
              onChange={(e) => {
                setFormElevenLabsId(e.target.value);
                if (!formName.trim() || formName.startsWith('ElevenLabs ')) {
                  const shortName = e.target.value.split(' (')[0];
                  setFormName(`ElevenLabs ${shortName}`);
                }
              }}
              options={COMFYUI_ELEVENLABS_VOICES}
            />
          )}
          <Input
            label={t('settings.voice.dialog.speedLabel')}
            type="number"
            value={formSpeed}
            onChange={(e) => setFormSpeed(e.target.value)}
            hint={t('settings.voice.dialog.speedHint')}
          />
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => { setDialogOpen(false); resetForm(); }}>
            {t('settings.voice.dialog.cancel')}
          </Button>
          <Button
            variant="primary"
            loading={creating}
            disabled={!formName.trim()}
            onClick={() => void handleCreate()}
          >
            {t('settings.voice.dialog.submit')}
          </Button>
        </DialogFooter>
      </Dialog>
      {cloneOpen && (
        <VoiceCloneDialog
          onClose={() => setCloneOpen(false)}
          onDone={() => {
            setCloneOpen(false);
            void fetchProfiles();
          }}
        />
      )}
    </div>
  );
}
