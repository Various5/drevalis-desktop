import { Card } from '@/components/ui/Card';
import type { BackupListResponse } from './types';
import { hostHintFromVmLabel } from './utils';

interface ScheduleSectionProps {
  backupDirectoryAbs: BackupListResponse['backup_directory_abs'];
  backupDirectory: BackupListResponse['backup_directory'];
  backupDirectoryHostSource: BackupListResponse['backup_directory_host_source'];
  retention: BackupListResponse['retention'];
  autoEnabled: BackupListResponse['auto_enabled'];
}

export function ScheduleSection({
  backupDirectoryAbs,
  backupDirectory,
  backupDirectoryHostSource,
  retention,
  autoEnabled,
}: ScheduleSectionProps) {
  return (
    <Card className="p-6">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
        <div className="rounded bg-bg-elevated p-3">
          <div className="text-txt-muted uppercase tracking-wider mb-1">Directory (container)</div>
          <div className="text-txt-primary font-mono break-all">
            {backupDirectoryAbs || backupDirectory}
          </div>
          {backupDirectoryHostSource && (
            <>
              <div className="text-txt-muted uppercase tracking-wider mt-3 mb-1">On host</div>
              <div className="text-accent font-mono break-all">{backupDirectoryHostSource}</div>
              {hostHintFromVmLabel(backupDirectoryHostSource) && (
                <div className="mt-2 text-[11px] text-txt-secondary leading-relaxed">
                  {hostHintFromVmLabel(backupDirectoryHostSource)}
                </div>
              )}
            </>
          )}
        </div>
        <div className="rounded bg-bg-elevated p-3">
          <div className="text-txt-muted uppercase tracking-wider mb-1">Retention</div>
          <div className="text-txt-primary">Keep {retention} most recent</div>
        </div>
        <div className="rounded bg-bg-elevated p-3">
          <div className="text-txt-muted uppercase tracking-wider mb-1">Auto-backup</div>
          <div className={autoEnabled ? 'text-accent' : 'text-txt-secondary'}>
            {autoEnabled ? 'Nightly at 03:00 UTC' : 'Disabled'}
          </div>
        </div>
      </div>
      <p className="text-xs text-txt-muted mt-3">
        Configure via environment variables: <code>BACKUP_DIRECTORY</code>,{' '}
        <code>BACKUP_RETENTION</code>, <code>BACKUP_AUTO_ENABLED</code>. Mount a network share
        (SMB/NFS) into the container at the backup directory path to send backups off-box.
        Can't find a backup on your host? Run{' '}
        <code className="text-[11px]">
          docker inspect -f &quot;&#123;&#123;range .Mounts&#125;&#125;&#123;&#123;if eq .Destination
          \&quot;/app/storage\&quot;&#125;&#125;&#123;&#123;.Source&#125;&#125;&#123;&#123;end&#125;&#125;&#123;&#123;end&#125;&#125;&quot;
          $(docker ps -q --filter &quot;name=app&quot;)
        </code>{' '}
        to see the exact host directory Docker bound when the container started.
      </p>
    </Card>
  );
}
