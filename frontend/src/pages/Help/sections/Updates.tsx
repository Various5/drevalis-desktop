import { Zap, ChevronRight } from 'lucide-react';
import { SectionHeading, SubHeading, CodeBlock } from './_shared';

export function Updates() {
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
