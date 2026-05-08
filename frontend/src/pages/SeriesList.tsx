import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Plus, Layers, Sparkles } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/Button';
import { Input, Textarea } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { Dialog, DialogFooter } from '@/components/ui/Dialog';
import { Spinner } from '@/components/ui/Spinner';
import { SeriesCard } from '@/components/series/SeriesCard';
import { EmptyState } from '@/components/ui/EmptyState';
import { useToast } from '@/components/ui/Toast';
import { series as seriesApi } from '@/lib/api';
import { useSeries, useVoiceProfiles, queryKeys } from '@/lib/queries';
import type { SeriesCreate, SeriesGenerateResponse } from '@/types';

// ---------------------------------------------------------------------------
// Series List Page
// ---------------------------------------------------------------------------

function SeriesList() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const qc = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [creating, setCreating] = useState(false);

  // Form state
  const [formName, setFormName] = useState('');
  const [formDescription, setFormDescription] = useState('');
  const [formDuration, setFormDuration] = useState<'15' | '30' | '60'>('30');

  // AI Generate state
  const [aiDialogOpen, setAiDialogOpen] = useState(false);
  const [aiIdea, setAiIdea] = useState('');
  const [aiEpisodeCount, setAiEpisodeCount] = useState(10);
  const [aiDuration, setAiDuration] = useState(30);
  const [aiVoice, setAiVoice] = useState('');
  const [aiGenerating, setAiGenerating] = useState(false);
  const [aiError, setAiError] = useState('');
  const [aiResult, setAiResult] = useState<SeriesGenerateResponse | null>(null);

  // Phase 3.3: Query-driven loading. Mutations call ``invalidateQueries``
  // on the same keys so this list refreshes automatically.
  const seriesQ = useSeries();
  const voiceProfilesQ = useVoiceProfiles();
  const seriesList = seriesQ.data ?? [];
  const voiceProfiles = voiceProfilesQ.data ?? [];
  const loading = seriesQ.isPending;

  const refetchSeries = () => {
    void qc.invalidateQueries({ queryKey: queryKeys.series.all });
  };

  useEffect(() => {
    if (seriesQ.error) {
      toast.error('Failed to load series', { description: String(seriesQ.error) });
    }
    if (voiceProfilesQ.error) {
      toast.error('Failed to load voice profiles', { description: String(voiceProfilesQ.error) });
    }
  }, [seriesQ.error, voiceProfilesQ.error, toast]);

  const handleCreate = async () => {
    if (!formName.trim()) return;
    setCreating(true);
    try {
      const payload: SeriesCreate = {
        name: formName.trim(),
        description: formDescription.trim() || undefined,
        target_duration_seconds: Number(formDuration) as 15 | 30 | 60,
      };
      await seriesApi.create(payload);
      setDialogOpen(false);
      setFormName('');
      setFormDescription('');
      setFormDuration('30');
      toast.success('Series created');
      refetchSeries();
    } catch (err) {
      toast.error('Failed to create series', { description: String(err) });
    } finally {
      setCreating(false);
    }
  };

  const handleAiGenerate = async () => {
    if (!aiIdea.trim() || aiIdea.trim().length < 10) return;
    setAiGenerating(true);
    setAiError('');
    try {
      // Start async job
      const { job_id } = await seriesApi.generate({
        idea: aiIdea.trim(),
        episode_count: aiEpisodeCount,
        target_duration_seconds: aiDuration,
        voice_profile_id: aiVoice || undefined,
      });

      // Poll for result
      const pollInterval = setInterval(async () => {
        try {
          const job = await seriesApi.getGenerateJob(job_id);
          if (job.status === 'done' && job.result) {
            clearInterval(pollInterval);
            setAiDialogOpen(false);
            setAiResult(job.result);
            toast.success('Series generated', { description: `${job.result.series_name} with ${job.result.episode_count} episodes` });
            setAiGenerating(false);
          } else if (job.status === 'failed' || job.status === 'cancelled') {
            clearInterval(pollInterval);
            setAiError(job.error || 'Series generation failed');
            setAiGenerating(false);
          }
        } catch (err) {
          clearInterval(pollInterval);
          setAiError('Lost connection to series generation job');
          toast.error('Lost connection to series generation job', { description: String(err) });
          setAiGenerating(false);
        }
      }, 3000);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : 'Failed to start series generation';
      setAiError(message);
      toast.error('Failed to start series generation', { description: String(err) });
      setAiGenerating(false);
    }
  };

  const resetAiForm = () => {
    setAiIdea('');
    setAiEpisodeCount(10);
    setAiDuration(30);
    setAiVoice('');
    setAiError('');
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <Spinner size="lg" />
      </div>
    );
  }

  return (
    <div>
      {/* Header — banner already shows "Series"; keep subtitle + CTAs only. */}
      <div className="flex items-center justify-between mb-6 gap-3 flex-wrap">
        <p className="text-sm text-txt-secondary">
          Manage your content series and their default configurations.
        </p>
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            onClick={() => {
              resetAiForm();
              setAiDialogOpen(true);
            }}
          >
            <Sparkles size={14} />
            AI Generate
          </Button>
          <Button variant="primary" onClick={() => setDialogOpen(true)}>
            <Plus size={14} />
            New Series
          </Button>
        </div>
      </div>

      {/* Grid */}
      {seriesList.length === 0 ? (
        <EmptyState
          icon={Layers}
          title="No series yet"
          description="Create your first series to start generating episodes."
          action={
            <div className="flex items-center gap-2">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => {
                  resetAiForm();
                  setAiDialogOpen(true);
                }}
              >
                <Sparkles size={14} />
                AI Generate
              </Button>
              <Button
                variant="primary"
                size="sm"
                onClick={() => setDialogOpen(true)}
              >
                <Plus size={14} />
                Create Series
              </Button>
            </div>
          }
        />
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {seriesList.map((s) => (
            <SeriesCard key={s.id} series={s} />
          ))}
        </div>
      )}

      {/* Create Dialog */}
      <Dialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        title="Create New Series"
        description="Set up a new content series with default settings."
      >
        <div className="space-y-4">
          <Input
            label="Series Name"
            placeholder="e.g., History Facts, Science Explained..."
            value={formName}
            onChange={(e) => setFormName(e.target.value)}
            autoFocus
          />
          <Textarea
            label="Description"
            placeholder="Brief description of this series..."
            value={formDescription}
            onChange={(e) => setFormDescription(e.target.value)}
          />
          <Select
            label="Target Duration"
            value={formDuration}
            onChange={(e) =>
              setFormDuration(e.target.value as '15' | '30' | '60')
            }
            options={[
              { value: '15', label: '15 seconds' },
              { value: '30', label: '30 seconds' },
              { value: '60', label: '60 seconds' },
            ]}
          />
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setDialogOpen(false)}>
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={creating}
            disabled={!formName.trim()}
            onClick={() => void handleCreate()}
          >
            Create Series
          </Button>
        </DialogFooter>
      </Dialog>

      {/* AI Generate Dialog */}
      <Dialog
        open={aiDialogOpen}
        onClose={() => {
          if (!aiGenerating) setAiDialogOpen(false);
        }}
        title="AI Series Creator"
        description="Describe your idea and let AI generate a complete series with episodes."
        maxWidth="lg"
      >
        <div className="space-y-4">
          <div>
            <label className="text-xs font-display font-medium text-txt-secondary block mb-1">
              Describe your series idea
            </label>
            <textarea
              value={aiIdea}
              onChange={(e) => setAiIdea(e.target.value)}
              className="w-full min-h-[120px] bg-bg-elevated border border-border rounded-lg p-3 text-sm text-txt-primary placeholder:text-txt-tertiary focus:border-accent focus:ring-1 focus:ring-accent/30 outline-none resize-y"
              placeholder="e.g., A fun series about medieval history facts. Each episode reveals one surprising thing about life in the Middle Ages. Energetic narration style with humor."
              autoFocus
              disabled={aiGenerating}
            />
            <p className="text-xs text-txt-tertiary mt-1">
              Be specific about the topic, style, and what makes each episode
              unique. Minimum 10 characters.
            </p>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-display font-medium text-txt-secondary block mb-1">
                Number of Episodes
              </label>
              <input
                type="number"
                value={aiEpisodeCount}
                onChange={(e) =>
                  setAiEpisodeCount(
                    Math.max(1, Math.min(50, parseInt(e.target.value) || 10)),
                  )
                }
                min={1}
                max={50}
                disabled={aiGenerating}
                className="w-full h-8 px-2.5 text-sm text-txt-primary bg-bg-elevated border border-border rounded placeholder:text-txt-tertiary focus:border-accent focus:shadow-accent-glow transition-all duration-fast"
              />
            </div>
            <Select
              label="Duration per Episode"
              value={String(aiDuration)}
              onChange={(e) => setAiDuration(parseInt(e.target.value))}
              disabled={aiGenerating}
              options={[
                { value: '15', label: '15 seconds' },
                { value: '30', label: '30 seconds' },
                { value: '60', label: '60 seconds' },
              ]}
            />
          </div>

          <Select
            label="Voice Profile (optional)"
            value={aiVoice}
            onChange={(e) => setAiVoice(e.target.value)}
            disabled={aiGenerating}
            options={[
              { value: '', label: 'Assign later' },
              ...voiceProfiles.map((v) => ({
                value: v.id,
                label: v.name,
              })),
            ]}
          />

          {aiError && (
            <div className="p-3 bg-error/10 border border-error/30 rounded-lg">
              <p className="text-sm text-error">{aiError}</p>
            </div>
          )}

          {aiGenerating && (
            <div className="p-3 bg-accent/10 border border-accent/30 rounded-lg flex items-center gap-3">
              <Spinner size="sm" />
              <div>
                <p className="text-sm text-txt-primary font-medium">
                  Generating series...
                </p>
                <p className="text-xs text-txt-tertiary">
                  The AI is creating your series and episode ideas. This may take
                  30-60 seconds.
                </p>
              </div>
            </div>
          )}
        </div>
        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => setAiDialogOpen(false)}
            disabled={aiGenerating}
          >
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={aiGenerating}
            disabled={!aiIdea.trim() || aiIdea.trim().length < 10}
            onClick={() => void handleAiGenerate()}
          >
            <Sparkles size={14} />
            Generate Series
          </Button>
        </DialogFooter>
      </Dialog>

      {/* AI Result Dialog */}
      {aiResult && (
        <Dialog
          open={!!aiResult}
          onClose={() => {
            setAiResult(null);
            refetchSeries();
          }}
          title="Series Created!"
          maxWidth="lg"
        >
          <div className="space-y-3">
            <div className="p-3 bg-green-500/10 border border-green-500/30 rounded-lg">
              <h3 className="font-display font-semibold text-txt-primary">
                {aiResult.series_name}
              </h3>
              <p className="text-sm text-txt-secondary mt-1">
                {aiResult.episode_count} episodes created
              </p>
            </div>
            <div className="max-h-[300px] overflow-y-auto space-y-2">
              {aiResult.episodes.map((ep, i) => (
                <div key={i} className="p-2 bg-bg-elevated rounded text-sm">
                  <span className="font-display font-medium text-txt-primary">
                    {i + 1}. {ep.title}
                  </span>
                  <p className="text-xs text-txt-tertiary mt-0.5">{ep.topic}</p>
                </div>
              ))}
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="ghost"
              onClick={() => {
                setAiResult(null);
                refetchSeries();
              }}
            >
              Close
            </Button>
            <Button
              variant="primary"
              onClick={() => {
                const seriesId = aiResult.series_id;
                setAiResult(null);
                refetchSeries();
                navigate(`/series/${seriesId}`);
              }}
            >
              Go to Series
            </Button>
          </DialogFooter>
        </Dialog>
      )}
    </div>
  );
}

export default SeriesList;
