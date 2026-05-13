import { HardDrive, ChevronRight } from 'lucide-react';
import { SectionHeading, SubHeading, Warning } from './_shared';

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
        Enable auto-backup in <strong className="text-txt-primary">Settings &rarr; Backup</strong>. The worker
        runs a backup every night at 03:00 UTC and prunes to the most recent N archives
        (default 7, configurable on the same page).
      </p>

      <SubHeading id="br-restore" title="Restoring an Archive" />
      <Warning>Restore is destructive. It truncates every user table (series, episodes, audiobooks, tokens) and overwrites storage files.</Warning>
      <ol className="space-y-2 text-sm text-txt-secondary ml-4 mb-4 list-decimal list-inside">
        <li>Settings -&gt; Backup -&gt; Restore from archive.</li>
        <li>Select the <code className="font-mono text-xs">.tar.gz</code> (from another install or a previous backup).</li>
        <li>Type <code className="font-mono text-xs">RESTORE</code> in the confirmation field.</li>
        <li>Click Restore. The app will refresh once the server-side restore completes.</li>
      </ol>

      <SubHeading id="br-location" title="Where Backups Live" />
      <p className="text-sm text-txt-secondary mb-3">
        Archives are written under your user-data dir &mdash;
        <code className="font-mono text-xs">%LOCALAPPDATA%\Drevalis\storage\backups\</code> on Windows,
        <code className="font-mono text-xs">~/Library/Application Support/Drevalis/storage/backups/</code> on macOS,
        <code className="font-mono text-xs">~/.local/share/Drevalis/storage/backups/</code> on Linux. Copy the
        <code className="font-mono text-xs">.tar.gz</code> off-box to a NAS / cloud storage as part of your
        own backup hygiene.
      </p>

      <SubHeading id="br-encryption" title="Encryption Keys & Cross-Install Migration" />
      <p className="text-sm text-txt-secondary mb-3">
        Archive manifests include a hash of the install's encryption key (stored in your OS keychain). Restoring into a machine with a different key is refused by default &mdash; OAuth tokens and API keys would be un-decryptable.
      </p>
      <ul className="space-y-2 text-sm text-txt-secondary ml-4 mb-4">
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Migrating a full install</strong> &mdash; export the encryption key from Settings &rarr; Backup on the source machine and import it on the target before restoring.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Partial restore (new install, keep only content)</strong> &mdash; tick <strong className="text-txt-primary">Allow different encryption key</strong> at restore time; you will need to re-enter YouTube OAuth, ElevenLabs API key, etc.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Never lose the encryption key</strong> &mdash; without it, backups are effectively encrypted-at-rest data you can't read.</li>
      </ul>
    </section>
  );
}

export default BackupRestore;
