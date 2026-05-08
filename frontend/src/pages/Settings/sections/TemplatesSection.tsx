import { useState, useEffect, useCallback } from 'react';
import {
  Plus,
  Trash2,
  Edit3,
  LayoutTemplate,
  Star,
  Layers,
  Subtitles,
  Volume2,
  Mic2,
} from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { EmptyState } from '@/components/ui/EmptyState';
import { Button } from '@/components/ui/Button';
import { Input, Textarea } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { Badge } from '@/components/ui/Badge';
import { Dialog, DialogFooter } from '@/components/ui/Dialog';
import { Spinner } from '@/components/ui/Spinner';
import { useToast } from '@/components/ui/Toast';
import { videoTemplates as videoTemplatesApi, voiceProfiles } from '@/lib/api';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const CAPTION_STYLE_PRESETS = [
  { value: 'default', label: 'Default' },
  { value: 'bold', label: 'Bold' },
  { value: 'minimal', label: 'Minimal' },
  { value: 'cinematic', label: 'Cinematic' },
  { value: 'neon', label: 'Neon' },
] as const;

export const MUSIC_MOOD_OPTIONS = [
  { value: 'upbeat', label: 'Upbeat' },
  { value: 'dramatic', label: 'Dramatic' },
  { value: 'calm', label: 'Calm' },
  { value: 'energetic', label: 'Energetic' },
  { value: 'mysterious', label: 'Mysterious' },
  { value: 'playful', label: 'Playful' },
  { value: 'inspirational', label: 'Inspirational' },
  { value: 'dark', label: 'Dark' },
  { value: 'romantic', label: 'Romantic' },
  { value: 'epic', label: 'Epic' },
  { value: 'chill', label: 'Chill' },
  { value: 'tense', label: 'Tense' },
] as const;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TemplateFormState {
  name: string;
  description: string;
  voice_profile_id: string;
  visual_style: string;
  caption_style: string;
  music_mood: string;
  music_volume_db: number;
  target_duration_seconds: number;
  is_default: boolean;
}

const DEFAULT_TEMPLATE_FORM: TemplateFormState = {
  name: '',
  description: '',
  voice_profile_id: '',
  visual_style: '',
  caption_style: 'default',
  music_mood: 'upbeat',
  music_volume_db: -14,
  target_duration_seconds: 30,
  is_default: false,
};

// Using a loose record type for template data from the API since the video
// templates API does not have a strongly-typed response schema on the frontend.
type TemplateRecord = Record<string, unknown> & { id: string; name?: string };

// ---------------------------------------------------------------------------
// TemplatesSection
// ---------------------------------------------------------------------------

export function TemplatesSection() {
  const { toast } = useToast();
  const [templates, setTemplates] = useState<TemplateRecord[]>([]);
  const [voices, setVoices] = useState<{ id: string; name: string }[]>([]);
  const [loading, setLoading] = useState(true);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingTemplate, setEditingTemplate] = useState<TemplateRecord | null>(null);
  const [saving, setSaving] = useState(false);
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  const [form, setForm] = useState<TemplateFormState>(DEFAULT_TEMPLATE_FORM);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      // ``videoTemplatesApi.list()`` now returns the generated
      // ``VideoTemplateResponse`` shape from ``@/types/api``. The
      // local ``TemplateRecord`` type predates that migration and is
      // intentionally permissive (``Record<string, unknown>``) so the
      // render-time runtime checks below stay correct. Bridge through
      // ``unknown`` rather than the (incompatible) direct cast.
      const [tmpl, vp] = await Promise.all([
        videoTemplatesApi.list().catch(() => [] as unknown as TemplateRecord[]),
        voiceProfiles.list().catch(() => []),
      ]);
      setTemplates(tmpl as unknown as TemplateRecord[]);
      setVoices(vp.map((v) => ({ id: v.id, name: v.name })));
    } catch (err) {
      toast.error('Failed to load templates', { description: String(err) });
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  const openCreateDialog = () => {
    setEditingTemplate(null);
    setForm(DEFAULT_TEMPLATE_FORM);
    setDialogOpen(true);
  };

  const openEditDialog = (tmpl: TemplateRecord) => {
    setEditingTemplate(tmpl);
    setForm({
      name: typeof tmpl.name === 'string' ? tmpl.name : '',
      description: typeof tmpl.description === 'string' ? tmpl.description : '',
      voice_profile_id: typeof tmpl.voice_profile_id === 'string' ? tmpl.voice_profile_id : '',
      visual_style: typeof tmpl.visual_style === 'string' ? tmpl.visual_style : '',
      caption_style: typeof tmpl.caption_style === 'string' ? tmpl.caption_style : 'default',
      music_mood: typeof tmpl.music_mood === 'string' ? tmpl.music_mood : 'upbeat',
      music_volume_db: typeof tmpl.music_volume_db === 'number' ? tmpl.music_volume_db : -14,
      target_duration_seconds: typeof tmpl.target_duration_seconds === 'number' ? tmpl.target_duration_seconds : 30,
      is_default: typeof tmpl.is_default === 'boolean' ? tmpl.is_default : false,
    });
    setDialogOpen(true);
  };

  const handleSave = async () => {
    if (!form.name.trim()) return;
    setSaving(true);
    try {
      // Backend schema (VideoTemplateCreate) requires ``music_enabled``
      // and prefers ``null`` over ``undefined`` for unset optional
      // strings — matches the FastAPI Optional[str] = None pattern that
      // the openapi-typescript schema reflects as ``string | null``.
      const payload = {
        name: form.name.trim(),
        description: form.description.trim() || null,
        voice_profile_id: form.voice_profile_id || null,
        visual_style: form.visual_style.trim() || null,
        caption_style: form.caption_style,
        music_enabled: true,
        music_mood: form.music_mood,
        music_volume_db: form.music_volume_db,
        target_duration_seconds: form.target_duration_seconds,
        is_default: form.is_default,
      };
      if (editingTemplate) {
        await videoTemplatesApi.update(editingTemplate.id, payload);
      } else {
        await videoTemplatesApi.create(payload);
      }
      toast.success(editingTemplate ? 'Template updated' : 'Template created');
      setDialogOpen(false);
      void fetchData();
    } catch (err) {
      toast.error(editingTemplate ? 'Failed to update template' : 'Failed to create template', { description: String(err) });
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    setDeleting(true);
    try {
      await videoTemplatesApi.remove(id);
      toast.success('Template deleted');
      setDeleteConfirmId(null);
      void fetchData();
    } catch (err) {
      toast.error('Failed to delete template', { description: String(err) });
    } finally {
      setDeleting(false);
    }
  };

  if (loading) return <Spinner />;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold text-txt-primary">Video Templates</h3>
          <p className="text-xs text-txt-secondary mt-0.5">
            Reusable configuration presets for voice, captions, music, and visual style.
          </p>
        </div>
        <Button variant="primary" size="sm" onClick={openCreateDialog}>
          <Plus size={14} />
          Create Template
        </Button>
      </div>

      {/* Empty state */}
      {templates.length === 0 && (
        <EmptyState
          icon={Layers}
          title="No templates yet"
          description="Create a template to reuse settings across multiple series."
          action={
            <Button variant="primary" size="sm" onClick={openCreateDialog}>
              <Plus size={14} />
              Create First Template
            </Button>
          }
        />
      )}

      {/* Templates grid */}
      {templates.length > 0 && (
        <div className="grid grid-cols-2 gap-3">
          {templates.map((tmpl) => {
            const tmplName = typeof tmpl.name === 'string' ? tmpl.name : '';
            const tmplDescription = typeof tmpl.description === 'string' ? tmpl.description : null;
            const tmplIsDefault = typeof tmpl.is_default === 'boolean' ? tmpl.is_default : false;
            const tmplUsageCount = typeof tmpl.usage_count === 'number' ? tmpl.usage_count : null;
            const tmplCaptionStyle = typeof tmpl.caption_style === 'string' ? tmpl.caption_style : null;
            const tmplMusicMood = typeof tmpl.music_mood === 'string' ? tmpl.music_mood : null;
            const tmplTargetDuration = typeof tmpl.target_duration_seconds === 'number' ? tmpl.target_duration_seconds : null;
            const tmplMusicVolume = tmpl.music_volume_db !== undefined ? tmpl.music_volume_db : undefined;
            const tmplVoiceProfileId = typeof tmpl.voice_profile_id === 'string' ? tmpl.voice_profile_id : null;
            const tmplVisualStyle = typeof tmpl.visual_style === 'string' ? tmpl.visual_style : null;
            return (
              <Card key={tmpl.id} padding="md" className="flex flex-col gap-3">
                {/* Card header */}
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <LayoutTemplate size={13} className="text-accent shrink-0" />
                      <h4 className="text-sm font-semibold text-txt-primary truncate">
                        {tmplName}
                      </h4>
                      {tmplIsDefault && (
                        <Star
                          size={11}
                          className="text-warning shrink-0"
                          aria-label="Default template"
                        />
                      )}
                    </div>
                    {tmplDescription && (
                      <p className="text-[11px] text-txt-secondary mt-0.5 line-clamp-2">
                        {tmplDescription}
                      </p>
                    )}
                  </div>
                  {tmplUsageCount !== null && (
                    <Badge variant="neutral" className="text-[10px] shrink-0">
                      {tmplUsageCount} uses
                    </Badge>
                  )}
                </div>

                {/* Settings pills */}
                <div className="flex flex-wrap gap-1.5">
                  {tmplCaptionStyle && (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-accent/10 text-accent text-[10px] font-medium border border-accent/20">
                      <Subtitles size={9} />
                      {tmplCaptionStyle}
                    </span>
                  )}
                  {tmplMusicMood && (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-bg-elevated text-txt-secondary text-[10px] font-medium border border-border">
                      <Volume2 size={9} />
                      {tmplMusicMood}
                    </span>
                  )}
                  {tmplTargetDuration !== null && (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-bg-elevated text-txt-secondary text-[10px] font-medium border border-border">
                      {tmplTargetDuration}s
                    </span>
                  )}
                  {tmplMusicVolume !== undefined && (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-bg-elevated text-txt-secondary text-[10px] font-medium border border-border">
                      {String(tmplMusicVolume)} dB
                    </span>
                  )}
                  {tmplVoiceProfileId && (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-bg-elevated text-txt-secondary text-[10px] font-medium border border-border">
                      <Mic2 size={9} />
                      {voices.find((v) => v.id === tmplVoiceProfileId)?.name ?? 'Voice'}
                    </span>
                  )}
                </div>

                {/* Visual style preview */}
                {tmplVisualStyle && (
                  <p className="text-[10px] text-txt-tertiary line-clamp-2 italic border-l-2 border-border pl-2">
                    {tmplVisualStyle}
                  </p>
                )}

                {/* Actions */}
                <div className="mt-auto flex items-center gap-2 pt-1">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="flex-1"
                    onClick={() => openEditDialog(tmpl)}
                    aria-label={`Edit template ${tmplName}`}
                  >
                    <Edit3 size={12} />
                    Edit
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setDeleteConfirmId(tmpl.id)}
                    aria-label={`Delete template ${tmplName}`}
                    className="text-error hover:bg-error-muted"
                  >
                    <Trash2 size={12} />
                  </Button>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      {/* Create / Edit dialog */}
      <Dialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        title={editingTemplate ? 'Edit Template' : 'Create Template'}
        description={
          editingTemplate
            ? 'Update the template settings below.'
            : 'Define a reusable configuration preset for your series.'
        }
      >
        <div className="space-y-4">
          {/* Name */}
          <Input
            label="Name"
            required
            placeholder="e.g. Sci-Fi Shorts, Dark Drama..."
            value={form.name}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            autoFocus
          />

          {/* Description */}
          <Textarea
            label="Description"
            placeholder="Optional description of this template..."
            value={form.description}
            onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
            rows={2}
          />

          {/* Voice profile */}
          <Select
            label="Voice Profile"
            value={form.voice_profile_id}
            onChange={(e) => setForm((f) => ({ ...f, voice_profile_id: e.target.value }))}
            options={[
              { value: '', label: 'No voice preference' },
              ...voices.map((v) => ({ value: v.id, label: v.name })),
            ]}
          />

          {/* Visual style */}
          <Textarea
            label="Visual Style"
            placeholder="Describe the visual aesthetic: color palette, lighting, mood, art style..."
            value={form.visual_style}
            onChange={(e) => setForm((f) => ({ ...f, visual_style: e.target.value }))}
            rows={2}
          />

          {/* Caption style */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-txt-secondary">Caption Style</label>
            <div className="flex flex-wrap gap-1.5">
              {CAPTION_STYLE_PRESETS.map((preset) => (
                <button
                  key={preset.value}
                  type="button"
                  onClick={() => setForm((f) => ({ ...f, caption_style: preset.value }))}
                  className={[
                    'px-3 py-1.5 rounded-md text-xs font-medium border transition-colors duration-fast',
                    form.caption_style === preset.value
                      ? 'border-accent bg-accent/10 text-accent'
                      : 'border-border bg-bg-elevated text-txt-secondary hover:bg-bg-hover hover:text-txt-primary',
                  ].join(' ')}
                >
                  {preset.label}
                </button>
              ))}
            </div>
          </div>

          {/* Music mood */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-txt-secondary">Music Mood</label>
            <div className="flex flex-wrap gap-1.5">
              {MUSIC_MOOD_OPTIONS.map((mood) => (
                <button
                  key={mood.value}
                  type="button"
                  onClick={() => setForm((f) => ({ ...f, music_mood: mood.value }))}
                  className={[
                    'px-3 py-1.5 rounded-md text-xs font-medium border transition-colors duration-fast',
                    form.music_mood === mood.value
                      ? 'border-accent bg-accent/10 text-accent'
                      : 'border-border bg-bg-elevated text-txt-secondary hover:bg-bg-hover hover:text-txt-primary',
                  ].join(' ')}
                >
                  {mood.label}
                </button>
              ))}
            </div>
          </div>

          {/* Music volume */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-txt-secondary">
              Music Volume: {form.music_volume_db} dB
            </label>
            <div className="flex items-center gap-3 h-8">
              <input
                type="range"
                min={-20}
                max={-6}
                step={1}
                value={form.music_volume_db}
                onChange={(e) =>
                  setForm((f) => ({ ...f, music_volume_db: Number(e.target.value) }))
                }
                aria-label="Music volume in decibels"
                className="w-full accent-accent h-1.5 bg-bg-elevated rounded-full appearance-none cursor-pointer
                  [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3.5 [&::-webkit-slider-thumb]:h-3.5
                  [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-accent [&::-webkit-slider-thumb]:shadow-sm
                  [&::-webkit-slider-thumb]:cursor-pointer [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-bg-base"
              />
              <span className="text-xs text-txt-tertiary font-mono w-10 text-right shrink-0">
                {form.music_volume_db} dB
              </span>
            </div>
            <p className="text-[10px] text-txt-tertiary">
              Lower values make the music quieter relative to narration
            </p>
          </div>

          {/* Target duration */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-txt-secondary">
              Target Duration: {form.target_duration_seconds}s
            </label>
            <div className="flex items-center gap-3 h-8">
              <input
                type="range"
                min={15}
                max={120}
                step={5}
                value={form.target_duration_seconds}
                onChange={(e) =>
                  setForm((f) => ({ ...f, target_duration_seconds: Number(e.target.value) }))
                }
                aria-label="Target video duration in seconds"
                className="w-full accent-accent h-1.5 bg-bg-elevated rounded-full appearance-none cursor-pointer
                  [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3.5 [&::-webkit-slider-thumb]:h-3.5
                  [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-accent [&::-webkit-slider-thumb]:shadow-sm
                  [&::-webkit-slider-thumb]:cursor-pointer [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-bg-base"
              />
              <span className="text-xs text-txt-tertiary font-mono w-10 text-right shrink-0">
                {form.target_duration_seconds}s
              </span>
            </div>
          </div>

          {/* Set as default */}
          <div className="flex items-center gap-3 py-1">
            <button
              type="button"
              role="checkbox"
              aria-checked={form.is_default}
              onClick={() => setForm((f) => ({ ...f, is_default: !f.is_default }))}
              className={[
                'relative w-9 h-5 rounded-full transition-colors duration-fast shrink-0',
                form.is_default ? 'bg-accent' : 'bg-bg-active',
              ].join(' ')}
            >
              <span
                className={[
                  'absolute top-0.5 w-4 h-4 rounded-full bg-white shadow-sm transition-transform duration-fast',
                  form.is_default ? 'translate-x-4' : 'translate-x-0.5',
                ].join(' ')}
              />
            </button>
            <div>
              <label className="text-sm font-medium text-txt-primary">
                Set as default template
              </label>
              <p className="text-[10px] text-txt-tertiary">
                Applied automatically when creating new series.
              </p>
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => setDialogOpen(false)}>
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={saving}
            disabled={!form.name.trim()}
            onClick={() => void handleSave()}
          >
            {editingTemplate ? 'Save Changes' : 'Create Template'}
          </Button>
        </DialogFooter>
      </Dialog>

      {/* Delete confirmation dialog */}
      <Dialog
        open={deleteConfirmId !== null}
        onClose={() => setDeleteConfirmId(null)}
        title="Delete Template"
        description="Are you sure? This template will be permanently removed. Series that used it will keep their current settings."
      >
        <DialogFooter>
          <Button variant="ghost" onClick={() => setDeleteConfirmId(null)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            loading={deleting}
            onClick={() => deleteConfirmId && void handleDelete(deleteConfirmId)}
          >
            <Trash2 size={13} />
            Delete Template
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}
