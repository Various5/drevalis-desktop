import { useNavigate } from 'react-router-dom';
import { Loader2, CheckCircle2 } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { JobProgressBar } from '@/components/jobs/JobProgressBar';
import type { GenerationJobListItem, ProgressMessage } from '@/types';

// ---------------------------------------------------------------------------
// ActiveJobsWidget — active jobs panel on the Dashboard
// ---------------------------------------------------------------------------

interface ActiveJobsWidgetProps {
  activeJobs: GenerationJobListItem[];
  latestByEpisode: Record<string, Record<string, ProgressMessage>>;
}

export function ActiveJobsWidget({
  activeJobs,
  latestByEpisode,
}: ActiveJobsWidgetProps) {
  const navigate = useNavigate();

  if (activeJobs.length === 0) {
    return (
      <Card padding="md" className="flex flex-col items-center justify-center">
        <div className="text-center py-6">
          <CheckCircle2 size={28} className="text-txt-tertiary mx-auto mb-2" />
          <p className="text-sm font-display text-txt-secondary font-medium">All clear</p>
          <p className="text-xs text-txt-tertiary mt-0.5">No active jobs running</p>
        </div>
      </Card>
    );
  }

  const jobsByEpisode = activeJobs.reduce<Record<string, GenerationJobListItem[]>>(
    (acc, job) => {
      const key = job.episode_id;
      if (!acc[key]) acc[key] = [];
      acc[key]!.push(job);
      return acc;
    },
    {},
  );

  return (
    <Card padding="md" className="h-full">
      <CardHeader>
        <CardTitle>
          <span className="flex items-center gap-2 font-display">
            <Loader2 size={16} className="animate-spin text-accent" />
            Active Jobs ({activeJobs.length})
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          {Object.entries(jobsByEpisode).map(([episodeId, epJobs]) => {
            const wsProgress = latestByEpisode[episodeId] ?? {};
            const apiProgress: Record<
              string,
              { status: string; progress_pct: number; message: string }
            > = {};
            for (const job of epJobs) {
              apiProgress[job.step] = {
                status: job.status,
                progress_pct: job.progress_pct,
                message: job.error_message ?? '',
              };
            }
            const merged = { ...apiProgress };
            for (const [step, msg] of Object.entries(wsProgress)) {
              merged[step] = msg;
            }

            return (
              <div
                key={episodeId}
                className="surface p-3 cursor-pointer hover:border-border-hover transition-colors"
                onClick={() => navigate(`/episodes/${episodeId}`)}
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-display font-medium text-txt-primary truncate">
                    Episode {episodeId.slice(0, 8)}...
                  </span>
                  <Badge variant="generating" dot>
                    generating
                  </Badge>
                </div>
                <JobProgressBar
                  stepProgress={merged as Record<string, ProgressMessage>}
                  compact
                />
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
