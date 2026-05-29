import { Download, RefreshCw, Trash2 } from 'lucide-react';
import { Trans, useTranslation } from 'react-i18next';
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
  const { t } = useTranslation();
  return (
    <Card className="p-6">
      <div className="flex items-center justify-between mb-3">
        <h4 className="font-semibold">{t('settings.backup.archives.heading', { count: archives.length })}</h4>
        <Button size="sm" variant="ghost" onClick={onRefresh} disabled={isRestoring}>
          <RefreshCw className="w-3.5 h-3.5 mr-1" />
          {t('settings.backup.archives.refresh')}
        </Button>
      </div>
      {archives.length === 0 ? (
        <div className="py-12 text-center text-sm text-txt-muted">
          <Trans
            i18nKey="settings.backup.archives.empty"
            components={{ 1: <strong className="text-txt-primary" /> }}
          />
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
