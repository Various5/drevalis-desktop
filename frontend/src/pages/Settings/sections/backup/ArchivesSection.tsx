import { Download, RefreshCw, Trash2 } from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import type { BackupArchive } from './types';
import { formatBytes } from './utils';

interface ArchivesSectionProps {
  archives: BackupArchive[];
  isRestoring: boolean;
  onRefresh: () => void;
  onDownload: (filename: string) => void;
  onDelete: (filename: string) => void;
}

export function ArchivesSection({
  archives,
  isRestoring,
  onRefresh,
  onDownload,
  onDelete,
}: ArchivesSectionProps) {
  return (
    <Card className="p-6">
      <div className="flex items-center justify-between mb-3">
        <h4 className="font-semibold">Existing archives ({archives.length})</h4>
        <Button size="sm" variant="ghost" onClick={onRefresh} disabled={isRestoring}>
          <RefreshCw className="w-3.5 h-3.5 mr-1" />
          Refresh
        </Button>
      </div>
      {archives.length === 0 ? (
        <div className="py-12 text-center text-sm text-txt-muted">
          No backups yet. Click <strong className="text-txt-primary">Backup now</strong> to create
          your first one.
        </div>
      ) : (
        <div className="space-y-2">
          {archives.map((a) => (
            <div
              key={a.filename}
              className="flex items-center justify-between gap-4 p-3 rounded bg-bg-elevated"
            >
              <div className="min-w-0">
                <div className="font-mono text-sm truncate">{a.filename}</div>
                <div className="text-xs text-txt-muted">
                  {new Date(a.created_at).toLocaleString()} &middot; {formatBytes(a.size_bytes)}
                </div>
              </div>
              <div className="flex gap-2 shrink-0">
                <Button size="sm" variant="ghost" onClick={() => onDownload(a.filename)}>
                  <Download className="w-4 h-4" />
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => onDelete(a.filename)}
                  className="text-error hover:bg-error/10"
                >
                  <Trash2 className="w-4 h-4" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
