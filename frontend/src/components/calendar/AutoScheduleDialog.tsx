import { useEffect, useState } from 'react';
import { Sparkles, Eye } from 'lucide-react';
import { Dialog, DialogFooter } from '@/components/ui/Dialog';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { Spinner } from '@/components/ui/Spinner';
import { useToast } from '@/components/ui/Toast';
import { schedule as scheduleApi, series as seriesApi } from '@/lib/api';
import type { SeriesListItem } from '@/types';

type Cadence = 'daily' | 'every_n_days' | 'weekly';

interface PlannedSlot {
  episode_id: string;
  episode_title: string;
  scheduled_at: string;
  privacy: string;
  youtube_channel_id: string | null;
}

interface AutoScheduleResponse {
  series_id: string;
  cadence: string;
  planned: PlannedSlot[];
  persisted: boolean;
  skipped_already_scheduled: string[];
}

const CADENCE_OPTIONS = [
  { value: 'daily', label: 'Every day' },
  { value: 'every_n_days', label: 'Every N days' },
  { value: 'weekly', label: 'Weekly (rotates allowed weekdays)' },
];

const EPISODE_FILTER_OPTIONS = [
  { value: 'all_unuploaded', label: 'Review + Exported (all unuploaded)' },
  { value: 'review', label: 'Review only' },
];

const PRIVACY_OPTIONS = [
  { value: 'private', label: 'Private' },
  { value: 'unlisted', label: 'Unlisted' },
  { value: 'public', label: 'Public' },
];

export interface AutoScheduleDialogProps {
  open: boolean;
  onClose: () => void;
  onScheduled: () => void;
  /** Pre-select a series (e.g. when opening from Series detail). */
  defaultSeriesId?: string;
}

/**
 * Dialog for the v0.27.0 auto-schedule endpoint. Lets the operator pick a
 * series + cadence + start date and either preview the plan (dry-run) or
 * persist the slots.
 *
 * The first slot honours the target channel's ``upload_days`` allow-list
 * and ``upload_time``; subsequent slots step by cadence. Episodes that
 * already have a scheduled YouTube post are skipped server-side.
 */
export function AutoScheduleDialog({
  open,
  onClose,
  onScheduled,
  defaultSeriesId,
}: AutoScheduleDialogProps) {
  const { toast } = useToast();
  const [seriesList, setSeriesList] = useState<SeriesListItem[]>([]);
  const [seriesLoading, setSeriesLoading] = useState(false);
  const [seriesId, setSeriesId] = useState<string>(defaultSeriesId ?? '');
  const [cadence, setCadence] = useState<Cadence>('daily');
  const [everyN, setEveryN] = useState(2);
  const [startAt, setStartAt] = useState<string>(() => {
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    tomorrow.setHours(9, 0, 0, 0);
    // Format as a value an <input type="datetime-local"> understands.
    const tzOffsetMin = tomorrow.getTimezoneOffset();
    const local = new Date(tomorrow.getTime() - tzOffsetMin * 60 * 1000);
    return local.toISOString().slice(0, 16);
  });
  const [episodeFilter, setEpisodeFilter] = useState<'review' | 'all_unuploaded'>(
    'all_unuploaded',
  );
  const [privacy, setPrivacy] = useState<'public' | 'unlisted' | 'private'>(
    'private',
  );
  const [descTemplate, setDescTemplate] = useState('');
  const [tagsTemplate, setTagsTemplate] = useState('');
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<AutoScheduleResponse | null>(null);

  useEffect(() => {
    if (!open) return;
    setPreview(null);
    setSeriesLoading(true);
    seriesApi
      .list()
      .then((data) => setSeriesList(data))
      .catch((err) =>
        toast.error('Failed to load series', {
          description: err?.message ?? String(err),
        }),
      )
      .finally(() => setSeriesLoading(false));
  }, [open, toast]);

  useEffect(() => {
    if (defaultSeriesId) setSeriesId(defaultSeriesId);
  }, [defaultSeriesId]);

  const submit = async (dryRun: boolean) => {
    if (!seriesId) {
      toast.error('Pick a series first');
      return;
    }
    setBusy(true);
    try {
      // ``startAt`` is in the user's local browser timezone; the
      // backend normalises naïve datetimes against ``app_timezone``.
      const startIso = new Date(startAt).toISOString();
      const result = await scheduleApi.autoScheduleSeries(seriesId, {
        cadence,
        every_n: cadence === 'every_n_days' ? everyN : 1,
        start_at: startIso,
        episode_filter: episodeFilter,
        privacy,
        description_template: descTemplate || undefined,
        tags_template: tagsTemplate || undefined,
        dry_run: dryRun,
      });
      if (dryRun) {
        setPreview(result as AutoScheduleResponse);
        toast.info('Preview', {
          description: `${(result as AutoScheduleResponse).planned.length} slot(s) would be created.`,
        });
      } else {
        const r = result as AutoScheduleResponse;
        toast.success('Scheduled', {
          description: `${r.planned.length} episode(s) scheduled across the calendar.${
            r.skipped_already_scheduled.length
              ? ` ${r.skipped_already_scheduled.length} skipped (already scheduled).`
              : ''
          }`,
        });
        onScheduled();
        onClose();
      }
    } catch (err: any) {
      toast.error('Auto-schedule failed', {
        description: err?.detail || err?.message || String(err),
      });
    } finally {
      setBusy(false);
    }
  };

  // Build series options dynamically (loaded from API).
  const seriesOptions = seriesList.map((s) => ({
    value: s.id,
    label: s.name,
  }));

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Auto-schedule a series"
      maxWidth="lg"
    >
      <div className="space-y-4">
        <div className="text-sm text-txt-secondary">
          Distribute review-ready unuploaded episodes across the calendar.
          The first slot lands on the channel's first allowed weekday at
          its configured upload time.
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2">
            {seriesLoading ? (
              <div className="flex items-center gap-2 text-txt-tertiary text-xs">
                <Spinner size="sm" /> loading series…
              </div>
            ) : (
              <Select
                label="Series"
                value={seriesId}
                onChange={(e) => setSeriesId(e.target.value)}
                placeholder="— pick a series —"
                options={seriesOptions}
              />
            )}
          </div>

          <Select
            label="Cadence"
            value={cadence}
            onChange={(e) => setCadence(e.target.value as Cadence)}
            options={CADENCE_OPTIONS}
          />

          {cadence === 'every_n_days' ? (
            <Input
              label="N (days)"
              type="number"
              min={1}
              max={30}
              value={everyN}
              onChange={(e) =>
                setEveryN(Math.max(1, Math.min(30, Number(e.target.value))))
              }
            />
          ) : (
            <div />
          )}

          <Input
            label="Start at"
            type="datetime-local"
            value={startAt}
            onChange={(e) => setStartAt(e.target.value)}
          />

          <Select
            label="Which episodes"
            value={episodeFilter}
            onChange={(e) =>
              setEpisodeFilter(e.target.value as 'review' | 'all_unuploaded')
            }
            options={EPISODE_FILTER_OPTIONS}
          />

          <Select
            label="Privacy"
            value={privacy}
            onChange={(e) =>
              setPrivacy(e.target.value as 'public' | 'unlisted' | 'private')
            }
            options={PRIVACY_OPTIONS}
          />

          <div className="col-span-2">
            <Input
              label="Description template (optional)"
              value={descTemplate}
              onChange={(e) => setDescTemplate(e.target.value)}
              placeholder="🔔 Subscribe for more!"
            />
          </div>

          <div className="col-span-2">
            <Input
              label="Tags template (comma-separated)"
              value={tagsTemplate}
              onChange={(e) => setTagsTemplate(e.target.value)}
              placeholder="ai, shorts, tutorial"
            />
          </div>
        </div>

        {preview && (
          <div className="border border-border rounded-md p-3 bg-bg-elevated max-h-64 overflow-auto">
            <div className="text-xs text-txt-secondary mb-2">
              <strong className="text-txt-primary">Preview</strong> — these
              are the slots that will be created. Click "Schedule" to
              persist.
            </div>
            {preview.planned.length === 0 && (
              <div className="text-xs text-txt-tertiary italic">
                No episodes match — they may all be scheduled already
                (skipped: {preview.skipped_already_scheduled.length}).
              </div>
            )}
            <ul className="text-xs text-txt-primary space-y-1">
              {preview.planned.map((slot) => (
                <li key={slot.episode_id} className="flex justify-between gap-3">
                  <span className="truncate">{slot.episode_title}</span>
                  <span className="text-txt-secondary whitespace-nowrap">
                    {new Date(slot.scheduled_at).toLocaleString()}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <DialogFooter>
        <Button variant="ghost" onClick={onClose} disabled={busy}>
          Cancel
        </Button>
        <Button
          variant="ghost"
          onClick={() => submit(true)}
          disabled={busy || !seriesId}
        >
          <Eye size={14} className="mr-1.5" />
          Preview
        </Button>
        <Button onClick={() => submit(false)} disabled={busy || !seriesId}>
          {busy ? (
            <Spinner size="sm" />
          ) : (
            <Sparkles size={14} className="mr-1.5" />
          )}
          Schedule
        </Button>
      </DialogFooter>
    </Dialog>
  );
}
