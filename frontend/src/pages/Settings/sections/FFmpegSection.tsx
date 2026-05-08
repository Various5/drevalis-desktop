import { useState, useEffect } from 'react';
import { Card } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Spinner } from '@/components/ui/Spinner';
import { settings as settingsApi } from '@/lib/api';
import type { FFmpegInfo } from '@/types';

export function FFmpegSection() {
  const [ffmpeg, setFfmpeg] = useState<FFmpegInfo | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    settingsApi
      .ffmpeg()
      .then(setFfmpeg)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Spinner />;

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold text-txt-primary">FFmpeg</h3>

      {ffmpeg ? (
        <Card padding="md">
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <Badge variant={ffmpeg.available ? 'success' : 'error'}>
                {ffmpeg.available ? 'Available' : 'Not Available'}
              </Badge>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <span className="text-xs text-txt-tertiary">Path</span>
                <p className="text-sm text-txt-secondary font-mono mt-0.5">
                  {ffmpeg.ffmpeg_path}
                </p>
              </div>
              {ffmpeg.version && (
                <div>
                  <span className="text-xs text-txt-tertiary">Version</span>
                  <p className="text-sm text-txt-secondary mt-0.5">
                    {ffmpeg.version}
                  </p>
                </div>
              )}
            </div>
            {ffmpeg.message && (
              <p className="text-xs text-txt-tertiary">{ffmpeg.message}</p>
            )}
          </div>
        </Card>
      ) : (
        <Card padding="md">
          <p className="text-sm text-txt-secondary">
            Unable to fetch FFmpeg information.
          </p>
        </Card>
      )}
    </div>
  );
}
