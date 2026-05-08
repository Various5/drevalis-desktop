import { useState, useMemo } from 'react';
import { FileText, ImageOff, Mic, RefreshCw, Save, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { Card } from '@/components/ui/Card';
import { Input, Textarea } from '@/components/ui/Input';
import { Dialog, DialogFooter } from '@/components/ui/Dialog';
import { SEOScorePanel } from '@/components/episode/SEOScorePanel';
import { EmptyState } from '@/components/ui/EmptyState';
import { episodes as episodesApi } from '@/lib/api';
import { useToast } from '@/components/ui/Toast';
import { useUnsavedWarning } from '@/hooks/useUnsavedWarning';
import type { Episode, VoiceProfile } from '@/types';
import type { SceneDataExtended, EditedScene } from './helpers';

// ---------------------------------------------------------------------------
// Raw JSON Editor (private to this file — not used outside ScriptTab)
// ---------------------------------------------------------------------------

function RawJsonEditor({
  text,
  onChangeText,
  saving,
  onSave,
  onCancel,
}: {
  text: string;
  onChangeText: (v: string) => void;
  saving: boolean;
  onSave: () => void;
  onCancel: () => void;
}) {
  return (
    <Card padding="md" className="border-accent/30">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-medium text-txt-secondary">Raw JSON Editor</span>
        <div className="flex gap-2">
          <Button variant="ghost" size="sm" onClick={onCancel}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="sm"
            loading={saving}
            onClick={onSave}
          >
            <Save size={12} />
            Save
          </Button>
        </div>
      </div>
      <Textarea
        value={text}
        onChange={(e) => onChangeText(e.target.value)}
        className="font-mono text-xs min-h-[300px]"
      />
    </Card>
  );
}

// ---------------------------------------------------------------------------
// ScriptTab
// ---------------------------------------------------------------------------

export function ScriptTab({
  episode,
  scenes,
  onRefresh,
  episodeId,
  voiceProfiles,
  epVoiceId,
  setEpVoiceId,
}: {
  episode: Episode;
  scenes: SceneDataExtended[];
  onRefresh: () => void;
  episodeId: string;
  voiceProfiles: VoiceProfile[];
  epVoiceId: string;
  setEpVoiceId: (v: string) => void;
}) {
  // Map scene number → image URL so each script segment can render
  // its corresponding generated thumbnail next to the editable text.
  const sceneImageBySceneNumber = new Map<number, string>();
  for (const s of scenes) {
    if (s.imageUrl) sceneImageBySceneNumber.set(s.sceneNumber, s.imageUrl);
  }
  const { toast } = useToast();
  const [revoicingInline, setRevoicingInline] = useState(false);
  const [editedScenes, setEditedScenes] = useState<Record<number, EditedScene>>({});
  const [savingScene, setSavingScene] = useState<number | null>(null);
  const [deletingScene, setDeletingScene] = useState<number | null>(null);
  const [regeneratingScene, setRegeneratingScene] = useState<number | null>(null);
  const [deleteConfirmScene, setDeleteConfirmScene] = useState<number | null>(null);
  const [showRawEditor, setShowRawEditor] = useState(false);
  const [rawText, setRawText] = useState('');
  const [savingRaw, setSavingRaw] = useState(false);

  // Warn about unsaved script edits
  const hasUnsavedScriptEdits = useMemo(
    () => Object.keys(editedScenes).length > 0 || showRawEditor,
    [editedScenes, showRawEditor],
  );
  useUnsavedWarning(hasUnsavedScriptEdits);

  if (!episode.script) {
    return (
      <EmptyState
        icon={FileText}
        title="No script generated yet"
        description="Generate the episode to create a script."
      />
    );
  }

  const scriptData = episode.script as Record<string, unknown>;
  const segments = (scriptData['scenes'] ?? scriptData['segments']) as
    | Array<Record<string, unknown>>
    | undefined;

  if (!Array.isArray(segments) || segments.length === 0) {
    return (
      <div className="space-y-3">
        <div className="flex justify-end">
          <Button variant="ghost" size="sm" onClick={() => {
            setRawText(JSON.stringify(episode.script, null, 2));
            setShowRawEditor(true);
          }}>
            Edit Raw JSON
          </Button>
        </div>
        <EmptyState
          icon={FileText}
          title="Script has no scenes"
          description="Edit the raw JSON to add scene data."
        />
        {showRawEditor && (
          <RawJsonEditor
            text={rawText}
            onChangeText={setRawText}
            saving={savingRaw}
            onSave={async () => {
              setSavingRaw(true);
              try {
                const parsed = JSON.parse(rawText);
                await episodesApi.updateScript(episode.id, { script: parsed });
                setShowRawEditor(false);
                toast.success('Script saved');
                onRefresh();
              } catch (err) {
                toast.error('Failed to save script', { description: String(err) });
              } finally {
                setSavingRaw(false);
              }
            }}
            onCancel={() => setShowRawEditor(false)}
          />
        )}
      </div>
    );
  }

  const updateEditedScene = (idx: number, field: string, value: unknown) => {
    setEditedScenes((prev) => ({
      ...prev,
      [idx]: {
        ...prev[idx],
        [field]: value,
      },
    }));
  };

  const isSceneModified = (idx: number) => {
    return editedScenes[idx] !== undefined && Object.keys(editedScenes[idx]).length > 0;
  };

  const saveScene = async (sceneNumber: number, idx: number) => {
    const edits = editedScenes[idx];
    if (!edits) return;
    setSavingScene(sceneNumber);
    try {
      await episodesApi.updateScene(episode.id, sceneNumber, edits);
      setEditedScenes((prev) => {
        const next = { ...prev };
        delete next[idx];
        return next;
      });
      toast.success('Script saved');
      onRefresh();
    } catch (err) {
      toast.error('Failed to save scene', { description: String(err) });
    } finally {
      setSavingScene(null);
    }
  };

  const handleDeleteScene = async (sceneNumber: number) => {
    setDeletingScene(sceneNumber);
    try {
      await episodesApi.deleteScene(episode.id, sceneNumber);
      setDeleteConfirmScene(null);
      toast.success('Scene deleted');
      onRefresh();
    } catch (err) {
      toast.error('Failed to delete scene', { description: String(err) });
    } finally {
      setDeletingScene(null);
    }
  };

  const handleRegenerateScene = async (sceneNumber: number) => {
    setRegeneratingScene(sceneNumber);
    try {
      const seg = segments[sceneNumber - 1];
      const prompt = seg ? (seg['visual_prompt'] as string | undefined) : undefined;
      await episodesApi.regenerateScene(episode.id, sceneNumber, prompt ?? undefined);
      toast.success('Scene regeneration started');
      onRefresh();
    } catch (err) {
      toast.error('Failed to regenerate scene', { description: String(err) });
    } finally {
      setRegeneratingScene(null);
    }
  };

  return (
    <div className="space-y-4">
      {/* SEO heuristics — deterministic, no LLM call. Updates when the
          episode.updated_at changes (post-save, post-regeneration, etc.). */}
      <SEOScorePanel episodeId={episodeId} refreshKey={Date.parse(episode.updated_at)} />

      {/* Voice Control Panel */}
      <Card className="p-3">
        <div className="flex items-center justify-between mb-2">
          <h4 className="text-xs font-semibold text-txt-secondary flex items-center gap-1.5">
            <Mic size={13} /> Voice Settings
          </h4>
        </div>
        <div className="space-y-2">
          <div>
            <label className="text-[10px] text-txt-tertiary block mb-1">Voice Profile</label>
            <select
              value={epVoiceId}
              onChange={(e) => {
                setEpVoiceId(e.target.value);
                void episodesApi.update(episodeId, {
                  override_voice_profile_id: e.target.value || null,
                } as any);
              }}
              className="w-full bg-bg-elevated border border-border rounded px-2.5 py-1.5 text-sm text-txt-primary focus:outline-none focus:border-accent"
              aria-label="Select voice profile for this episode"
            >
              <option value="">Series default</option>
              {voiceProfiles.map(v => (
                <option key={v.id} value={v.id}>{v.name} ({v.provider})</option>
              ))}
            </select>
          </div>
          {(episode.status === 'review' || episode.status === 'exported') && (
            <Button
              variant="secondary"
              size="sm"
              loading={revoicingInline}
              onClick={async () => {
                setRevoicingInline(true);
                try {
                  await episodesApi.regenerateVoice(episodeId, epVoiceId || undefined);
                  toast.success('Voice regeneration started');
                  onRefresh();
                } catch (err) {
                  toast.error('Failed to regenerate voice', { description: String(err) });
                } finally {
                  setRevoicingInline(false);
                }
              }}
              aria-label="Regenerate voice audio for this episode"
            >
              <Mic size={12} />
              Regenerate Voice
            </Button>
          )}
        </div>
      </Card>

      <div className="flex justify-end">
        <Button variant="ghost" size="sm" onClick={() => {
          setRawText(JSON.stringify(episode.script, null, 2));
          setShowRawEditor(true);
        }}>
          Edit Raw JSON
        </Button>
      </div>

      {showRawEditor && (
        <RawJsonEditor
          text={rawText}
          onChangeText={setRawText}
          saving={savingRaw}
          onSave={async () => {
            setSavingRaw(true);
            try {
              const parsed = JSON.parse(rawText);
              await episodesApi.updateScript(episode.id, { script: parsed });
              setShowRawEditor(false);
              toast.success('Script saved');
              onRefresh();
            } catch (err) {
              toast.error('Failed to save script', { description: String(err) });
            } finally {
              setSavingRaw(false);
            }
          }}
          onCancel={() => setShowRawEditor(false)}
        />
      )}

      {segments.map((seg, idx) => {
        const sceneNumber = idx + 1;
        const narration = (seg['narration'] as string) ?? (seg['text'] as string) ?? '';
        const visualPrompt = (seg['visual_prompt'] as string) ?? '';
        const durationSeconds = (seg['duration_seconds'] as number) ?? 3;
        const keywords = (seg['keywords'] as string[]) ?? [];

        return (
          <Card key={sceneNumber} padding="md" className="relative group">
            {/* Scene header */}
            <div className="flex items-center justify-between mb-3">
              <Badge variant="script">Scene {sceneNumber}</Badge>
              <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                <Button
                  variant="ghost"
                  size="sm"
                  loading={regeneratingScene === sceneNumber}
                  onClick={() => void handleRegenerateScene(sceneNumber)}
                >
                  <RefreshCw size={12} />
                  Regenerate
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-error hover:text-error/80"
                  onClick={() => setDeleteConfirmScene(sceneNumber)}
                >
                  <Trash2 size={12} />
                </Button>
              </div>
            </div>

            {/* Body — thumbnail on the left when one exists, edit
                fields on the right. On narrow screens we stack so the
                fields aren't squeezed. */}
            <div className="flex flex-col sm:flex-row gap-3">
              {(() => {
                const img = sceneImageBySceneNumber.get(sceneNumber);
                return (
                  <div className="sm:w-32 shrink-0">
                    <div className="aspect-video rounded-md bg-bg-base border border-border overflow-hidden">
                      {img ? (
                        <img
                          src={img}
                          alt={`Scene ${sceneNumber}`}
                          className="w-full h-full object-cover"
                          loading="lazy"
                        />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center">
                          <ImageOff size={16} className="text-txt-tertiary" />
                        </div>
                      )}
                    </div>
                  </div>
                );
              })()}
              <div className="flex-1 min-w-0 space-y-3">
                {/* Narration (editable) */}
                <div>
                  <label className="text-xs text-txt-tertiary">Narration</label>
                  <Textarea
                    value={editedScenes[idx]?.narration ?? narration}
                    onChange={(e) => updateEditedScene(idx, 'narration', e.target.value)}
                    className="mt-1 text-sm min-h-[60px]"
                    rows={2}
                  />
                </div>

                {/* Visual Prompt (editable) */}
                <div>
                  <label className="text-xs text-txt-tertiary">Visual Prompt</label>
                  <Textarea
                    value={editedScenes[idx]?.visual_prompt ?? visualPrompt}
                    onChange={(e) => updateEditedScene(idx, 'visual_prompt', e.target.value)}
                    className="mt-1 text-xs font-mono min-h-[60px]"
                    rows={2}
                  />
                </div>
              </div>
            </div>

            {/* Duration + Keywords */}
            <div className="flex gap-4">
              <div>
                <label className="text-xs text-txt-tertiary">Duration</label>
                <Input
                  type="number"
                  value={editedScenes[idx]?.duration_seconds ?? durationSeconds}
                  onChange={(e) =>
                    updateEditedScene(idx, 'duration_seconds', parseFloat(e.target.value) || 0)
                  }
                  className="w-20 text-sm"
                  step={0.5}
                />
              </div>
              <div className="flex-1">
                <label className="text-xs text-txt-tertiary">Keywords</label>
                <Input
                  value={
                    editedScenes[idx]?.keywords !== undefined
                      ? editedScenes[idx].keywords!.join(', ')
                      : keywords.join(', ')
                  }
                  onChange={(e) =>
                    updateEditedScene(
                      idx,
                      'keywords',
                      e.target.value.split(',').map((k) => k.trim()).filter(Boolean),
                    )
                  }
                  className="text-sm"
                  placeholder="word1, word2, word3"
                />
              </div>
            </div>

            {/* Save button (shows when modified) */}
            {isSceneModified(idx) && (
              <Button
                variant="primary"
                size="sm"
                className="mt-3"
                loading={savingScene === sceneNumber}
                onClick={() => void saveScene(sceneNumber, idx)}
              >
                <Save size={12} />
                Save Changes
              </Button>
            )}
          </Card>
        );
      })}

      {/* Delete scene confirmation dialog */}
      <Dialog
        open={deleteConfirmScene !== null}
        onClose={() => setDeleteConfirmScene(null)}
        title={`Delete Scene ${deleteConfirmScene}?`}
      >
        <p className="text-sm text-txt-secondary">
          This will remove the scene from the script. This action cannot be undone.
        </p>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setDeleteConfirmScene(null)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            loading={deletingScene === deleteConfirmScene}
            onClick={() => {
              if (deleteConfirmScene !== null) {
                void handleDeleteScene(deleteConfirmScene);
              }
            }}
          >
            <Trash2 size={14} />
            Delete Scene
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}
