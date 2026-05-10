import { Zap, ChevronRight } from 'lucide-react';
import { isTauri } from '@/lib/tauri';
import { SectionHeading, SubHeading, CodeBlock } from './_shared';

export function Updates() {
  if (isTauri()) {
    return (
      <section id="updates" className="mb-16 scroll-mt-4">
        <SectionHeading id="updates-heading" icon={Zap} title="Updates" />

        <SubHeading id="updates-how" title="How Updates Work" />
        <p className="text-sm text-txt-secondary mb-3">
          Drevalis Creator Studio checks GitHub Releases for new versions. Updates are signed with
          a Tauri Ed25519 keypair and verified locally before they install &mdash; a tampered or
          unsigned installer will be rejected even if it reaches your machine.
        </p>
        <ul className="space-y-2 text-sm text-txt-secondary ml-4 mb-4">
          <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Background check on launch</strong> &mdash; the app pings the release feed shortly after startup. No telemetry, just a single GET to GitHub.</li>
          <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Signed differential install</strong> &mdash; Tauri downloads the new NSIS installer, verifies the .sig, then runs it with your prior install path preserved.</li>
          <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Your data is preserved</strong> &mdash; the SQLite database, storage directory, and OS-keychain secrets all live outside the install folder, so updates leave them untouched. Alembic migrations run on first launch of the new build.</li>
        </ul>

        <SubHeading id="updates-auto" title="In-App Update (Recommended)" />
        <ol className="space-y-2 text-sm text-txt-secondary ml-4 mb-4 list-decimal list-inside">
          <li>Settings &rarr; Updates.</li>
          <li>If a new version is listed, click <strong className="text-txt-primary">Download &amp; install</strong>.</li>
          <li>The app downloads the signed installer (a few hundred MB), then prompts to relaunch.</li>
          <li>After relaunch, the new build comes up with your existing data intact.</li>
        </ol>

        <SubHeading id="updates-manual" title="Manual Reinstall" />
        <p className="text-sm text-txt-secondary mb-3">
          If the in-app update fails, grab the latest installer from GitHub Releases and run it.
          You can install over the existing version &mdash; data is preserved.
        </p>
        <CodeBlock>{`https://github.com/Various5/drevalis-desktop/releases/latest`}</CodeBlock>

        <SubHeading id="updates-rollback" title="Rolling Back" />
        <p className="text-sm text-txt-secondary mb-4">
          If a new release breaks something, download the previous installer from the Releases
          page and run it &mdash; the NSIS installer will downgrade in place. Report the issue to{' '}
          <a href="mailto:support@drevalis.com" className="text-accent underline">support@drevalis.com</a>{' '}
          with the version and a log snippet from Settings &rarr; Diagnostics so we can fix it.
        </p>
      </section>
    );
  }

  return (
    <section id="updates" className="mb-16 scroll-mt-4">
      <SectionHeading id="updates-heading" icon={Zap} title="Updates" />

      <SubHeading id="updates-how" title="How Updates Work" />
      <p className="text-sm text-txt-secondary mb-3">
        The license server maintains a manifest of the latest stable version. Your install checks this endpoint on demand (Settings -&gt; Updates) and daily via the license heartbeat.
      </p>
      <ul className="space-y-2 text-sm text-txt-secondary ml-4 mb-4">
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Requires active license</strong> - the manifest endpoint returns 402 if your subscription has lapsed.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Docker images only</strong> - updates pull pre-built images from GHCR. No source-code compilation on your end.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Zero data loss</strong> - database volume + storage directory are preserved across updates. Alembic migrations run on boot of the new image.</li>
      </ul>

      <SubHeading id="updates-auto" title="In-App Update (Recommended)" />
      <ol className="space-y-2 text-sm text-txt-secondary ml-4 mb-4 list-decimal list-inside">
        <li>Settings -&gt; Updates.</li>
        <li>If a new version is listed, click <strong className="text-txt-primary">Update now</strong>.</li>
        <li>The updater sidecar pulls new images and restarts the stack (~60 seconds).</li>
        <li>The browser reconnects automatically once the health check passes.</li>
      </ol>

      <SubHeading id="updates-manual" title="Manual Update" />
      <CodeBlock>{`cd ~/Drevalis\ndocker compose pull\ndocker compose up -d`}</CodeBlock>

      <SubHeading id="updates-rollback" title="Rolling Back" />
      <p className="text-sm text-txt-secondary mb-3">
        If a new release breaks something, pin the previous version by editing <code className="font-mono text-xs">docker-compose.yml</code>:
      </p>
      <CodeBlock>{`# Change image lines from :stable to a specific tag, e.g. :0.1.7\nimage: ghcr.io/drevaliscs/creator-studio-app:0.1.7`}</CodeBlock>
      <p className="text-sm text-txt-secondary mb-4">
        Then <code className="font-mono text-xs">docker compose pull && docker compose up -d</code>. Report the issue to <a href="mailto:support@drevalis.com" className="text-accent underline">support@drevalis.com</a> with the version + a log snippet so we can fix it.
      </p>
    </section>
  );
}

export default Updates;
