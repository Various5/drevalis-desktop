import { useState } from 'react';
import { Download, FileArchive } from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { useToast } from '@/components/ui/Toast';
import { formatError } from '@/lib/api';

/**
 * DiagnosticsSection — lets an owner download a redacted diagnostics bundle
 * to send to support. The ZIP contains configuration (secrets redacted),
 * health status, recent logs, system info, and the current DB revision.
 */
export function DiagnosticsSection() {
  const { toast } = useToast();
  const [downloading, setDownloading] = useState(false);

  const onDownload = async () => {
    setDownloading(true);
    try {
      const res = await fetch('/api/v1/diagnostics/bundle');
      if (!res.ok) {
        const text = await res.text().catch(() => res.statusText);
        throw new Error(`${res.status}: ${text}`);
      }

      const blob = await res.blob();
      const dateStr = new Date().toISOString().slice(0, 10); // YYYY-MM-DD
      const filename = `drevalis-diagnostics-${dateStr}.zip`;

      const url = URL.createObjectURL(blob);
      try {
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = filename;
        anchor.style.display = 'none';
        document.body.appendChild(anchor);
        anchor.click();
        document.body.removeChild(anchor);
      } finally {
        // Revoke after a short delay so the download starts before the
        // object URL is released.
        setTimeout(() => URL.revokeObjectURL(url), 10_000);
      }

      toast.success('Diagnostics bundle downloaded', {
        description: filename,
      });
    } catch (err) {
      toast.error('Download failed', { description: formatError(err) });
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="space-y-6">
      <Card className="p-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="font-semibold text-lg flex items-center gap-2 mb-1">
              <FileArchive className="w-5 h-5" />
              Support Diagnostics
            </h3>
            <p className="text-sm text-txt-secondary">
              Download a ZIP bundle to send to support when reporting an issue. The
              bundle contains redacted configuration, health status, recent logs,
              system info, and the current database revision.
            </p>
            <ul className="mt-3 space-y-1 text-xs text-txt-muted list-disc list-inside">
              <li>
                <code>config.json</code> — all settings with secrets replaced by{' '}
                <code>***REDACTED***</code>
              </li>
              <li>
                <code>health.json</code> — database, FFmpeg, and Piper status
              </li>
              <li>
                <code>recent_logs.txt</code> — last 1000 log lines (if a log file is
                configured)
              </li>
              <li>
                <code>system.json</code> — Python version, platform, disk space
              </li>
              <li>
                <code>db_revision.txt</code> — current Alembic migration head
              </li>
            </ul>
          </div>
          <Button
            onClick={onDownload}
            disabled={downloading}
            variant="primary"
            className="shrink-0"
          >
            <Download className="w-4 h-4 mr-1.5" />
            {downloading ? 'Preparing...' : 'Download diagnostics'}
          </Button>
        </div>
      </Card>
    </div>
  );
}
