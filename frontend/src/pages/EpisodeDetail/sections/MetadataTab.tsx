import { Search } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { Card } from '@/components/ui/Card';
import type { Episode } from '@/types';

export function MetadataTab({ episode }: { episode: Episode }) {
  const seo = episode.metadata_?.seo as {
    virality_score?: number;
    title?: string;
    hook?: string;
    description?: string;
    hashtags?: string[];
    tags?: string[];
  } | undefined;

  return (
    <div className="space-y-4">
      {/* SEO Analysis — shown if SEO data has been generated */}
      {seo && (
        <Card padding="md" className="border-accent/20">
          <h4 className="text-sm font-semibold text-txt-primary mb-3 flex items-center gap-2">
            <Search size={14} className="text-accent" />
            SEO Analysis
          </h4>
          <div className="space-y-3">
            {typeof seo.virality_score === 'number' && (
              <div className="flex items-center gap-2">
                <span className="text-xs text-txt-secondary">Virality Score:</span>
                <Badge
                  variant={
                    seo.virality_score >= 7
                      ? 'success'
                      : seo.virality_score >= 5
                        ? 'warning'
                        : 'neutral'
                  }
                >
                  {seo.virality_score}/10
                </Badge>
              </div>
            )}
            {seo.title && (
              <div>
                <span className="text-xs text-txt-secondary block mb-0.5">Optimized Title:</span>
                <p className="text-sm text-txt-primary bg-bg-elevated px-2 py-1.5 rounded">
                  {seo.title}
                </p>
              </div>
            )}
            {seo.hook && (
              <div>
                <span className="text-xs text-txt-secondary block mb-0.5">Hook:</span>
                <p className="text-sm text-accent italic bg-bg-elevated px-2 py-1.5 rounded">
                  &quot;{seo.hook}&quot;
                </p>
              </div>
            )}
            {seo.hashtags && seo.hashtags.length > 0 && (
              <div>
                <span className="text-xs text-txt-secondary block mb-1">Hashtags:</span>
                <div className="flex flex-wrap gap-1">
                  {seo.hashtags.map((h) => (
                    <Badge key={h} variant="neutral">
                      {h}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </div>
        </Card>
      )}

      <Card padding="md">
        <h4 className="text-sm font-semibold text-txt-primary mb-3">
          Episode Info
        </h4>
        <div className="grid grid-cols-2 gap-3 text-sm">
          <div>
            <span className="text-txt-tertiary">ID</span>
            <p className="text-txt-secondary font-mono text-xs mt-0.5">
              {episode.id}
            </p>
          </div>
          <div>
            <span className="text-txt-tertiary">Series ID</span>
            <p className="text-txt-secondary font-mono text-xs mt-0.5">
              {episode.series_id}
            </p>
          </div>
          <div>
            <span className="text-txt-tertiary">Status</span>
            <div className="mt-0.5">
              <Badge variant={episode.status} dot>
                {episode.status}
              </Badge>
            </div>
          </div>
          <div>
            <span className="text-txt-tertiary">Base Path</span>
            <p className="text-txt-secondary font-mono text-xs mt-0.5">
              {episode.base_path ?? 'Not set'}
            </p>
          </div>
          <div>
            <span className="text-txt-tertiary">Created</span>
            <p className="text-txt-secondary text-xs mt-0.5">
              {new Date(episode.created_at).toLocaleString()}
            </p>
          </div>
          <div>
            <span className="text-txt-tertiary">Updated</span>
            <p className="text-txt-secondary text-xs mt-0.5">
              {new Date(episode.updated_at).toLocaleString()}
            </p>
          </div>
        </div>
      </Card>

      {/* Media Assets */}
      {episode.media_assets.length > 0 && (
        <Card padding="md">
          <h4 className="text-sm font-semibold text-txt-primary mb-3">
            Media Assets ({episode.media_assets.length})
          </h4>
          <div className="space-y-2">
            {episode.media_assets.map((asset) => (
              <div
                key={asset.id}
                className="flex items-center justify-between p-2 rounded bg-bg-hover text-xs"
              >
                <div className="flex items-center gap-2">
                  <Badge variant="neutral">{asset.asset_type}</Badge>
                  <span className="text-txt-secondary font-mono">
                    {asset.file_path.split('/').pop()}
                  </span>
                </div>
                <div className="flex items-center gap-3 text-txt-tertiary">
                  {asset.file_size_bytes && (
                    <span>
                      {(asset.file_size_bytes / 1024).toFixed(0)} KB
                    </span>
                  )}
                  {asset.duration_seconds && (
                    <span>{asset.duration_seconds.toFixed(1)}s</span>
                  )}
                  {asset.scene_number && (
                    <Badge variant="neutral">Scene {asset.scene_number}</Badge>
                  )}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Generation Jobs */}
      {episode.generation_jobs.length > 0 && (
        <Card padding="md">
          <h4 className="text-sm font-semibold text-txt-primary mb-3">
            Generation Jobs ({episode.generation_jobs.length})
          </h4>
          <div className="space-y-2">
            {episode.generation_jobs.map((job) => (
              <div
                key={job.id}
                className="flex items-center justify-between p-2 rounded bg-bg-hover text-xs"
              >
                <div className="flex items-center gap-2">
                  <Badge variant={job.step}>{job.step}</Badge>
                  <Badge variant={job.status as 'queued' | 'running' | 'done' | 'failed'} dot>
                    {job.status}
                  </Badge>
                  <span className="text-txt-tertiary font-mono">
                    {job.progress_pct}%
                  </span>
                </div>
                <div className="flex items-center gap-2 text-txt-tertiary">
                  {job.error_message && (
                    <span className="text-error max-w-xs text-truncate">
                      {job.error_message}
                    </span>
                  )}
                  {job.retry_count > 0 && (
                    <Badge variant="warning">
                      {job.retry_count} retries
                    </Badge>
                  )}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Generation Log */}
      {episode.generation_log && (
        <Card padding="md">
          <h4 className="text-sm font-semibold text-txt-primary mb-3">
            Generation Log
          </h4>
          <pre className="text-xs text-txt-secondary overflow-x-auto">
            {JSON.stringify(episode.generation_log, null, 2)}
          </pre>
        </Card>
      )}
    </div>
  );
}
