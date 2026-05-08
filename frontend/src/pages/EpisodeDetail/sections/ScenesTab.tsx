import { useState } from 'react';
import { Clock, FileText, ImageOff, Loader2, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Textarea } from '@/components/ui/Input';
import { Dialog, DialogFooter } from '@/components/ui/Dialog';
import { EmptyState } from '@/components/ui/EmptyState';
import { episodes as episodesApi } from '@/lib/api';
import { useToast } from '@/components/ui/Toast';
import type { Episode } from '@/types';
import type { SceneDataExtended } from './helpers';

export function ScenesTab({
  episode,
  scenes,
  onRefresh,
}: {
  episode: Episode;
  scenes: SceneDataExtended[];
  onRefresh: () => void;
}) {
  const { toast } = useToast();
  const [regeneratingScene, setRegeneratingScene] = useState<number | null>(null);
  const [editPromptScene, setEditPromptScene] = useState<number | null>(null);
  const [editPromptText, setEditPromptText] = useState('');

  if (scenes.length === 0) {
    return (
      <EmptyState
        icon={ImageOff}
        title="No scenes generated yet"
        description="Generate the script and scenes to see thumbnails here."
      />
    );
  }

  const handleRegenerateScene = async (sceneNumber: number, prompt?: string) => {
    setRegeneratingScene(sceneNumber);
    try {
      await episodesApi.regenerateScene(episode.id, sceneNumber, prompt);
      toast.success('Scene regeneration started');
      onRefresh();
    } catch (err) {
      toast.error('Failed to regenerate scene', { description: String(err) });
    } finally {
      setRegeneratingScene(null);
    }
  };

  const handleEditPromptSubmit = async () => {
    if (editPromptScene === null) return;
    await handleRegenerateScene(editPromptScene, editPromptText || undefined);
    setEditPromptScene(null);
    setEditPromptText('');
  };

  return (
    <>
      <div className="grid grid-cols-2 gap-3">
        {scenes.map((scene) => {
          const isRegenerating = regeneratingScene === scene.sceneNumber;

          return (
            <div
              key={scene.sceneNumber}
              className="surface-interactive relative overflow-hidden group"
            >
              {/* Thumbnail */}
              <div className="aspect-video bg-bg-base relative overflow-hidden">
                {scene.imageUrl ? (
                  <img
                    src={scene.imageUrl}
                    alt={`Scene ${scene.sceneNumber}`}
                    className="w-full h-full object-cover"
                  />
                ) : (
                  <div className="w-full h-full flex items-center justify-center">
                    <ImageOff size={24} className="text-txt-tertiary" />
                  </div>
                )}

                {/* Scene number badge */}
                <div className="absolute top-2 left-2">
                  <span className="badge bg-black/60 text-white backdrop-blur-sm">
                    #{scene.sceneNumber}
                  </span>
                </div>

                {/* Duration badge */}
                <div className="absolute top-2 right-2">
                  <span className="badge bg-black/60 text-white backdrop-blur-sm">
                    <Clock size={10} />
                    {scene.durationSeconds.toFixed(1)}s
                  </span>
                </div>

                {/* Generating spinner overlay */}
                {isRegenerating && (
                  <div className="absolute inset-0 bg-black/60 flex items-center justify-center">
                    <Loader2 size={24} className="text-white animate-spin" />
                  </div>
                )}

                {/* Hover overlay */}
                {!isRegenerating && (
                  <div className="absolute inset-0 bg-black/50 flex items-center justify-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={(e) => {
                        e.stopPropagation();
                        void handleRegenerateScene(scene.sceneNumber, scene.visualPrompt || undefined);
                      }}
                    >
                      <RefreshCw size={12} />
                      Regenerate
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={(e) => {
                        e.stopPropagation();
                        setEditPromptScene(scene.sceneNumber);
                        setEditPromptText(scene.visualPrompt);
                      }}
                    >
                      <FileText size={12} />
                      Edit Prompt
                    </Button>
                  </div>
                )}
              </div>

              {/* Prompt text */}
              <div className="p-2">
                <p className="text-xs text-txt-secondary text-clamp-2 leading-relaxed">
                  {scene.prompt}
                </p>
              </div>
            </div>
          );
        })}
      </div>

      {/* Edit Prompt Dialog */}
      <Dialog
        open={editPromptScene !== null}
        onClose={() => {
          setEditPromptScene(null);
          setEditPromptText('');
        }}
        title={`Edit Prompt - Scene ${editPromptScene}`}
      >
        <Textarea
          label="Visual Prompt"
          value={editPromptText}
          onChange={(e) => setEditPromptText(e.target.value)}
          className="font-mono text-xs min-h-[120px]"
          placeholder="Describe the visual for this scene..."
        />
        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => {
              setEditPromptScene(null);
              setEditPromptText('');
            }}
          >
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={regeneratingScene === editPromptScene}
            onClick={() => void handleEditPromptSubmit()}
          >
            <RefreshCw size={14} />
            Regenerate with Prompt
          </Button>
        </DialogFooter>
      </Dialog>
    </>
  );
}
