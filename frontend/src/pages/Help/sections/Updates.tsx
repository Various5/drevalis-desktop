import { Zap, ChevronRight } from 'lucide-react';
import { SectionHeading, SubHeading, CodeBlock } from './_shared';

export function Updates() {
  return (
    <section id="updates" className="mb-16 scroll-mt-4">
      <SectionHeading id="updates-heading" icon={Zap} title="Updates" />

      <SubHeading id="updates-how" title="How Updates Work" />
      <p className="text-sm text-txt-secondary mb-3">
        Drevalis checks GitHub Releases for new versions. Every installer is signed with a Tauri
        Ed25519 key and verified locally before it runs &mdash; an unsigned or tampered installer is rejected.
      </p>
      <ul className="space-y-2 text-sm text-txt-secondary ml-4 mb-4">
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Auto-check on launch</strong> &mdash; one GET to GitHub Releases, no telemetry.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Signed install</strong> &mdash; downloads the NSIS installer, verifies the signature, then runs it.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Your data is preserved</strong> &mdash; the SQLite DB, storage tree, and keychain secrets all live outside the install dir. Migrations run on first launch of the new build.</li>
      </ul>

      <SubHeading id="updates-auto" title="In-App Update (Recommended)" />
      <ol className="space-y-2 text-sm text-txt-secondary ml-4 mb-4 list-decimal list-inside">
        <li>Open <strong className="text-txt-primary">Settings &rarr; Updates</strong>.</li>
        <li>If a new version is listed, click <strong className="text-txt-primary">Download &amp; install</strong>.</li>
        <li>The app downloads the signed installer, then prompts to relaunch.</li>
      </ol>

      <SubHeading id="updates-manual" title="Manual Reinstall" />
      <p className="text-sm text-txt-secondary mb-3">
        If the in-app update fails, grab the latest installer from GitHub and run it &mdash; installing
        over an existing version preserves your data.
      </p>
      <CodeBlock>{`https://github.com/Various5/drevalis-desktop/releases/latest`}</CodeBlock>

      <SubHeading id="updates-rollback" title="Rolling Back" />
      <p className="text-sm text-txt-secondary mb-4">
        If a release breaks something, download the previous installer from the Releases page &mdash;
        NSIS will downgrade in place. Send the version and a log snippet from
        Settings &rarr; Diagnostics to{' '}
        <a href="mailto:support@drevalis.com" className="text-accent underline">support@drevalis.com</a>.
      </p>
    </section>
  );
}

export default Updates;
