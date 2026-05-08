import { HardDrive, ChevronRight } from 'lucide-react';
import { SectionHeading, SubHeading, Warning, CodeBlock } from './_shared';

export function BackupRestore() {
  return (
    <section id="backup-restore" className="mb-16 scroll-mt-4">
      <SectionHeading id="backup-restore-heading" icon={HardDrive} title="Backup & Restore" />

      <p className="text-sm text-txt-secondary leading-relaxed mb-4">
        Full-install backups bundle every database row (series, episodes, voice profiles, OAuth tokens, etc.) and your generated media (episodes/, audiobooks/, voice_previews/) into a single <code className="font-mono text-xs text-accent">.tar.gz</code>. Model files are NOT included - they re-download on first use.
      </p>

      <SubHeading id="br-manual" title="Manual Backup" />
      <ol className="space-y-2 text-sm text-txt-secondary ml-4 mb-4 list-decimal list-inside">
        <li>Settings -&gt; Backup.</li>
        <li>Click <strong className="text-txt-primary">Backup now</strong>.</li>
        <li>When done, click the download icon to save the archive to your desktop.</li>
      </ol>

      <SubHeading id="br-auto" title="Auto-Backup Schedule" />
      <p className="text-sm text-txt-secondary mb-3">
        Set <code className="font-mono text-xs">BACKUP_AUTO_ENABLED=true</code> in <code className="font-mono text-xs">.env</code> (via Docker Compose). The worker creates a backup every night at 03:00 UTC, pruning to the most recent <code className="font-mono text-xs">BACKUP_RETENTION</code> (default 7).
      </p>
      <CodeBlock>{`# .env\nBACKUP_AUTO_ENABLED=true\nBACKUP_RETENTION=14\nBACKUP_DIRECTORY=/app/storage/backups`}</CodeBlock>

      <SubHeading id="br-restore" title="Restoring an Archive" />
      <Warning>Restore is destructive. It truncates every user table (series, episodes, audiobooks, tokens) and overwrites storage files.</Warning>
      <ol className="space-y-2 text-sm text-txt-secondary ml-4 mb-4 list-decimal list-inside">
        <li>Settings -&gt; Backup -&gt; Restore from archive.</li>
        <li>Select the <code className="font-mono text-xs">.tar.gz</code> (from another install or a previous backup).</li>
        <li>Type <code className="font-mono text-xs">RESTORE</code> in the confirmation field.</li>
        <li>Click Restore. The app will refresh once the server-side restore completes.</li>
      </ol>

      <SubHeading id="br-smb" title="Off-Box: SMB / NFS Mount" />
      <p className="text-sm text-txt-secondary mb-3">
        To send backups to a NAS or network share, mount the share into the app container at <code className="font-mono text-xs">/app/storage/backups</code>:
      </p>
      <CodeBlock>{`# docker-compose.override.yml\nservices:\n  app:\n    volumes:\n      - type: bind\n        source: /mnt/nas/drevalis-backups\n        target: /app/storage/backups`}</CodeBlock>

      <SubHeading id="br-encryption" title="Encryption Keys & Cross-Install Migration" />
      <p className="text-sm text-txt-secondary mb-3">
        Archive manifests include a hash of the install's ENCRYPTION_KEY. Restoring into a machine with a different key is refused by default (OAuth tokens + API keys would be un-decryptable).
      </p>
      <ul className="space-y-2 text-sm text-txt-secondary ml-4 mb-4">
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Migrating a full install</strong> - copy the source install's <code className="font-mono text-xs">.env</code> (or at least <code className="font-mono text-xs">ENCRYPTION_KEY</code>) to the target before running restore.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Partial restore (new install, keep only content)</strong> - tick <strong className="text-txt-primary">Allow different ENCRYPTION_KEY</strong>; you will need to re-enter YouTube OAuth, ElevenLabs API key, etc.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Never lose your ENCRYPTION_KEY</strong> - without it, backups are effectively encrypted-at-rest data you can't read.</li>
      </ul>
    </section>
  );
}

export default BackupRestore;
